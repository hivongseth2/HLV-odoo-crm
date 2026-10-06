#!/usr/bin/env python3
"""Báo cáo đối soát MISA hằng ngày: gom số liệu lệch từ Odoo → Claude viết báo cáo → gửi về Odoo.

Chạy theo lịch Windows lúc 19h (xem references/worker-setup.md), không cần nằm chờ như worker điều
phối: báo cáo 1 lần/ngày, máy tắt thì hôm đó không có báo cáo và Odoo vẫn chạy bình thường.

Vì sao worker tự gom số liệu trước rồi mới gọi Claude: soát lý do từng đơn tốn 1–3 lệnh gọi MISA
và có thể tới vài trăm đơn — việc máy móc, làm bằng script nhanh và chắc hơn để Claude gọi từng
lệnh. Claude nhận 1 file JSONL, chỉ làm phần cần đầu óc: soát lại theo đơn những đơn tự sửa được,
xếp việc cho từng người, viết báo cáo, đề xuất gắn mã đề nghị.

Chạy tay:
    py misa_report_worker.py            # chạy thật
    py misa_report_worker.py --dry-run  # chỉ gom số liệu, ghi file, KHÔNG gọi Claude

Biến môi trường: như misa_ai.py, thêm CLAUDE_BIN (tuỳ chọn) nếu tự dò không ra claude.exe.
"""

import json
import logging
import os
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'dieu-phoi-giao-hang' / 'scripts'))
import misa_ai  # noqa: E402
from ai_worker import find_claude  # noqa: E402 — dùng chung cách dò claude.exe với worker điều phối

REPO_ROOT = HERE.parents[3]
DATA_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'hlv_misa_ai'
LOG_FILE = DATA_DIR / 'worker.log'
REVIEW_BATCH = 20
MAX_ORDERS = 600        # đủ mọi đơn lệch (30/09/2026: 382 đơn, soát ~4 phút/300 đơn)
CLAUDE_TIMEOUT = 2400

# Claude chỉ được đọc repo / file số liệu và gọi đúng lớp API. Không Write/Edit: chạy không ai
# nhìn, một lệnh sửa file ở đây là sửa code sản phẩm mà không ai duyệt.
MISA_SCRIPT = '.claude/skills/doi-soat-misa/scripts/misa_ai.py'
ALLOWED_TOOLS = ['Skill', 'Read', 'Glob', 'Grep', 'Bash(py %s:*)' % MISA_SCRIPT, 'Bash(python %s:*)' % MISA_SCRIPT]

_logger = logging.getLogger('hlv_misa_ai')


def collect(today):
    """Ghi file số liệu JSONL: dòng đầu là tổng quan, mỗi dòng sau là 1 đơn (DB + lý do từ MISA).
    Trả (đường dẫn file, tổng quan)."""
    scope = misa_ai.call('gap_orders', {'limit': MAX_ORDERS})
    orders = scope['orders']
    reviews = {}
    for start in range(0, len(orders), REVIEW_BATCH):
        batch = [row['id'] for row in orders[start:start + REVIEW_BATCH]]
        for review in misa_ai.call('review', {'order_ids': batch}):
            reviews[review['id']] = review
        _logger.info('Đã soát %s/%s đơn', min(start + REVIEW_BATCH, len(orders)), len(orders))
    header = {
        'report_date': today, 'order_count': scope['order_count'], 'total_gap': scope['total_gap'],
        'listed_orders': len(orders), 'pairs': scope['pairs'], 'last_report': misa_ai.call('last_report'),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / ('doi_soat_%s.jsonl' % today)
    with path.open('w', encoding='utf-8') as handle:
        handle.write(json.dumps(header, ensure_ascii=False) + '\n')
        for row in orders:
            handle.write(json.dumps(compact({**row, **reviews.get(row['id'], {})}), ensure_ascii=False) + '\n')
    return path, header


def compact(row):
    """Bỏ dòng HĐ hải quan ĐÃ khớp (chỉ giữ số dòng) — không cần cho báo cáo, mà 1 dòng JSONL dài
    quá 2.000 ký tự thì công cụ đọc file của Claude cắt mất phần sau (30/09/2026: DH…234923 có 30
    dòng hải quan đã khớp)."""
    customs = row.get('customs') or []
    row['customs'] = [line for line in customs if line.get('state') != 'matched']
    row['customs_matched_count'] = len(customs) - len(row['customs'])
    row.pop('partner_id', None)
    return row


def prompt_for(path, today):
    """Lời nhắc NGẮN — luật nằm trong skill (có lịch sử sửa), không nhân bản ở đây."""
    return ('Dùng skill doi-soat-misa để viết báo cáo đối soát MISA ngày %s từ file số liệu %s. '
            'Bắt buộc kết thúc bằng một lời gọi "misa_ai.py report".' % (today, path))


def run_claude(claude_bin, prompt):
    """Chạy Claude không tương tác. Trả None nếu trót lọt, hoặc chuỗi mô tả lỗi."""
    environment = dict(os.environ)
    environment['PATH'] = str(Path(sys.executable).parent) + os.pathsep + environment.get('PATH', '')
    try:
        completed = subprocess.run(
            # --add-dir: file số liệu nằm ngoài repo, không cấp thư mục thì Read bị từ chối khi chạy -p.
            [claude_bin, '-p', prompt, '--permission-mode', 'default', '--add-dir', str(DATA_DIR),
             '--allowed-tools', *ALLOWED_TOOLS],
            cwd=str(REPO_ROOT), env=environment, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=CLAUDE_TIMEOUT, check=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except subprocess.TimeoutExpired:
        return 'Claude chạy quá %s giây, đã dừng.' % CLAUDE_TIMEOUT
    except OSError as exc:
        return 'Không chạy được Claude: %s' % exc
    if completed.returncode != 0:
        return 'Claude thoát với mã %s: %s' % (completed.returncode, (completed.stderr or '')[-500:])
    return None


def fallback_report(header, error):
    """Claude hỏng thì vẫn gửi 1 báo cáo tối thiểu — người dùng thấy ngay hôm nay không có báo cáo
    AI và vì sao, thay vì tưởng không có gì lệch."""
    misa_ai.call('report', {
        'report_date': header['report_date'], 'order_count': header['order_count'],
        'total_gap': header['total_gap'], 'worker': socket.gethostname(),
        'body': '<p><b>AI chưa viết được báo cáo hôm nay:</b> %s</p><p>%s đơn lệch, tổng %s đ. Xem khung '
                '"Vì sao còn lệch" hoặc chạy bin/check_misa_invoice_gap_reasons.py.</p>' % (
                    error, header['order_count'], f"{header['total_gap']:,.0f}".replace(',', '.')),
    })


def main(argv):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO, encoding='utf-8',
                        format='%(asctime)s %(levelname)s %(message)s')
    today = date.today().isoformat()
    path, header = collect(today)
    _logger.info('Số liệu %s: %s đơn lệch, ghi %s', today, header['order_count'], path)
    if '--dry-run' in argv:
        print(path)
        return 0
    claude_bin = find_claude()
    error = None if claude_bin else 'không tìm thấy claude.exe (đặt biến CLAUDE_BIN)'
    if claude_bin:
        error = run_claude(claude_bin, prompt_for(path, today))
    last = misa_ai.call('last_report') or {}
    if last.get('report_date') == today and (header['last_report'] or {}).get('id') != last.get('id'):
        _logger.info('Xong báo cáo %s (#%s)', today, last['id'])
        return 0
    error = error or 'Claude chạy xong nhưng không gửi báo cáo.'
    _logger.error('Hỏng báo cáo %s: %s', today, error)
    fallback_report(header, error)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
