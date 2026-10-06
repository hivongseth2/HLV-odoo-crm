#!/usr/bin/env python3
"""Lớp gọi API đối soát MISA (controllers/misa_invoice_ai_controller.py) — MỘT file biết chuyện
"gọi bằng cách nào", SKILL.md chỉ nói gọi cái gì.

Đăng nhập bằng phiên Odoo của tài khoản worker (thuộc nhóm "Đối soát XHD"), giữ cookie trong
%LOCALAPPDATA%\\hlv_misa_ai\\session.txt để Claude gọi nhiều lệnh không phải đăng nhập lại mỗi
lần; phiên hết hạn thì tự đăng nhập lại 1 lần.

Dùng:
    py misa_ai.py gap_orders '{"limit": 300}'
    py misa_ai.py review '{"order_ids": [123, 456]}'
    py misa_ai.py refresh '{"order_ids": [123]}'
    py misa_ai.py last_report
    py misa_ai.py report @baocao.json        # body JSON từ file
    py misa_ai.py report - <<'EOF'           # hoặc từ stdin
    {...}
    EOF

Biến môi trường (thiếu thì lấy biến VTRACKING_* cùng tên của worker điều phối trên cùng máy):
    MISA_AI_BASE_URL   (VTRACKING_BASE_URL)        ví dụ https://hoanglongvu.odoo.com
    MISA_AI_DB         (VTRACKING_DB)
    MISA_AI_LOGIN      (VTRACKING_WORKER_LOGIN)    tài khoản phải thuộc nhóm "Đối soát XHD"
    MISA_AI_PASSWORD   (VTRACKING_WORKER_PASSWORD)

Thoát 0 khi thành công, 1 khi API báo lỗi, 2 khi cấu hình / kết nối sai.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# UA trình duyệt — Cloudflare trước Odoo production chặn UA mặc định của urllib (xem vt.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'dieu-phoi-giao-hang' / 'scripts'))
from vt import USER_AGENT  # noqa: E402

ROUTES = {'gap_orders', 'review', 'refresh', 'last_report', 'report'}
TIMEOUT = 300   # 1 lượt review gọi MISA cho tới 20 đơn
SESSION_FILE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'hlv_misa_ai' / 'session.txt'


def fail(message, code=2):
    print('LỖI: %s' % message, file=sys.stderr)
    raise SystemExit(code)


def env(name):
    return os.environ.get('MISA_AI_' + name) or os.environ.get({
        'BASE_URL': 'VTRACKING_BASE_URL', 'DB': 'VTRACKING_DB',
        'LOGIN': 'VTRACKING_WORKER_LOGIN', 'PASSWORD': 'VTRACKING_WORKER_PASSWORD',
    }[name]) or ''


class _KeepPostRedirect(urllib.request.HTTPRedirectHandler):
    """Theo chuyển hướng mà GIỮ POST + body. Mặc định urllib đổi POST thành GET và bỏ body khi gặp
    301/302 — Odoo nhận GET vào route JSON và trả "Request inferred type is compatible with
    ['http']" (case thật 30/09/2026: hoanglongvu-erp.com chuyển 301 sang www.hoanglongvu-erp.com)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        print('CẢNH BÁO: %s chuyển hướng tới %s — nên đặt MISA_AI_BASE_URL theo địa chỉ mới.'
              % (req.full_url, newurl), file=sys.stderr)
        # req.headers, KHÔNG header_items(): cái sau kèm Host cũ (không www) → Cloudflare chuyển
        # hướng lại chính nó, lặp mãi.
        return urllib.request.Request(newurl, data=req.data, headers=dict(req.headers), method=req.get_method())


_OPENER = urllib.request.build_opener(_KeepPostRedirect)


def _post(url, params, cookie=None):
    """JSON-RPC POST → (body đã parse, cookie phiên mới nếu Odoo trả)."""
    data = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params}).encode('utf-8')
    request = urllib.request.Request(url, data=data, method='POST', headers={
        'Content-Type': 'application/json', 'User-Agent': USER_AGENT, **({'Cookie': cookie} if cookie else {}),
    })
    try:
        with _OPENER.open(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read().decode('utf-8'))
            new_cookie = next((c.split(';')[0] for c in response.headers.get_all('Set-Cookie') or []
                               if c.startswith('session_id=')), None)
    except urllib.error.HTTPError as exc:
        fail('HTTP %s khi gọi %s: %s' % (exc.code, url, exc.read().decode('utf-8', 'replace')[:300]), 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        fail('Không kết nối được %s: %s' % (url, exc))
    return body, new_cookie


def login(base):
    db, user, password = env('DB'), env('LOGIN'), env('PASSWORD')
    if not (db and user and password):
        fail('Chưa đặt MISA_AI_DB / MISA_AI_LOGIN / MISA_AI_PASSWORD (hoặc VTRACKING_*).')
    body, cookie = _post(base + '/web/session/authenticate', {'db': db, 'login': user, 'password': password})
    if body.get('error') or not (body.get('result') or {}).get('uid') or not cookie:
        fail('Đăng nhập Odoo thất bại: %s' % (body.get('error') or body))
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(cookie, encoding='utf-8')
    return cookie


def call(route, params=None):
    """Gọi 1 route /misa_invoice/ai/<route>. Trả phần `data`; SystemExit khi API báo lỗi."""
    if route not in ROUTES:
        fail('Route không có: %s (chỉ %s)' % (route, ', '.join(sorted(ROUTES))))
    base = env('BASE_URL').rstrip('/')
    if not base:
        fail('Chưa đặt MISA_AI_BASE_URL (hoặc VTRACKING_BASE_URL).')
    cookie = SESSION_FILE.read_text(encoding='utf-8').strip() if SESSION_FILE.exists() else login(base)
    for attempt in (1, 2):
        body, _ = _post('%s/misa_invoice/ai/%s' % (base, route), params or {}, cookie)
        error = body.get('error')
        # Phiên hết hạn (Odoo trả lỗi SessionExpired) → đăng nhập lại đúng 1 lần.
        if error and attempt == 1 and 'Session' in json.dumps(error):
            cookie = login(base)
            continue
        if error:
            fail('%s' % ((error.get('data') or {}).get('message') or error.get('message') or error), 1)
        result = body.get('result') or {}
        if result.get('status') != 'success':
            fail(result.get('message') or result, 1)
        return result.get('data')
    return None


def read_body(argument):
    if not argument:
        return {}
    raw = sys.stdin.read() if argument == '-' else argument
    if argument.startswith('@'):
        raw = Path(argument[1:]).read_text(encoding='utf-8')
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        fail('Body không phải JSON hợp lệ: %s' % exc)


def main(argv):
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    if len(argv) < 2:
        fail('Dùng: misa_ai.py <%s> [body JSON | @file | -]' % '|'.join(sorted(ROUTES)))
    result = call(argv[1], read_body(argv[2] if len(argv) > 2 else ''))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
