#!/usr/bin/env python3
"""Máy này nằm chờ Odoo gọi, rồi cho Claude xử lý yêu cầu điều phối của nhân viên.

Vì sao chờ chứ không hỏi liên tục: Odoo chạy trên internet, máy này nằm sau router nên
Odoo không gọi vào được. Nên máy này mở MỘT websocket ra Odoo và giữ nó — đúng cách hộp
Odoo IoT làm. Có yêu cầu mới, Odoo đẩy xuống ngay, không tốn request nào lúc rảnh.

Chạy::

    py ai_worker.py            # chạy thật
    py ai_worker.py --once     # xử lý hết yêu cầu đang chờ rồi thoát (để thử)

Biến môi trường (thêm vào các biến VTRACKING_* mà vt.py đã dùng)::

    VTRACKING_DB                tên cơ sở dữ liệu Odoo
    VTRACKING_WORKER_LOGIN      tài khoản riêng cho worker (khai ở Cấu hình > Kết nối)
    VTRACKING_WORKER_PASSWORD   mật khẩu tài khoản đó
    CLAUDE_BIN                  (tuỳ chọn) đường dẫn claude.exe nếu tự dò không ra

Cần ``pip install websockets``. Mọi việc gọi API đi qua ``vt.py`` — file này không tự dựng
request nào, trừ lúc đăng nhập để mở websocket.
"""

import asyncio
import glob
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vt  # noqa: E402 — cùng thư mục, phải chèn sys.path trước

REPO_ROOT = Path(__file__).resolve().parents[4]
BUS_MESSAGE_TYPE = 'hlv_vtracking/ai_request'
CLAUDE_TIMEOUT = 900
RECONNECT_MIN, RECONNECT_MAX = 5, 120
LOG_FILE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'hlv_ai_worker' / 'worker.log'

# Claude chỉ được đọc repo và gọi đúng lớp API. Không cho Write/Edit: worker chạy không ai
# nhìn, một lệnh sửa file ở đây là sửa code sản phẩm mà không ai duyệt.
VT_SCRIPT = '.claude/skills/dieu-phoi-giao-hang/scripts/vt.py'
ALLOWED_TOOLS = [
    'Skill', 'Read', 'Glob', 'Grep',
    'Bash(py %s:*)' % VT_SCRIPT,
    'Bash(python %s:*)' % VT_SCRIPT,
]

_logger = logging.getLogger('hlv_ai_worker')


# ----------------------------------------------------------------------
# Hàm thuần — có test ở test_ai_worker.py
# ----------------------------------------------------------------------
def request_ids_from_frame(raw, message_type=BUS_MESSAGE_TYPE):
    """Khung websocket của Odoo -> (list id yêu cầu, id thông báo lớn nhất).

    Odoo gửi một mảng ``{'id', 'message': {'type', 'payload'}}``. Bỏ qua mọi loại tin khác
    (Odoo đẩy chung nhiều thứ trên kênh của một tài khoản). Khung hỏng trả về rỗng thay vì
    ném lỗi: một tin lạ không được làm chết worker.
    """
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return [], 0
    if not isinstance(items, list):
        return [], 0
    ids, last = [], 0
    for item in items:
        if not isinstance(item, dict):
            continue
        last = max(last, int(item.get('id') or 0))
        message = item.get('message') or {}
        if message.get('type') != message_type:
            continue
        payload = message.get('payload') or {}
        if payload.get('request_id'):
            ids.append(int(payload['request_id']))
    return ids, last


def prompt_for(request):
    """Lời nhắc gửi Claude cho một yêu cầu.

    Cố tình NGẮN và không chứa luật nghiệp vụ: luật nằm trong skill, ở repo, có lịch sử
    sửa. Nhét luật vào đây là tạo bản sao thứ hai sẽ lệch dần với bản kia.
    """
    return (
        'Dùng skill xu-ly-yeu-cau-dieu-phoi để xử lý yêu cầu điều phối #%(id)s '
        '(%(type)s, người gửi %(requester)s). Bắt buộc kết thúc bằng một lời gọi '
        'requests/%(id)s/answer. Nếu không xử lý được thì gọi requests/%(id)s/fail.'
        % {
            'id': request['id'],
            'type': request.get('request_type_label') or request.get('request_type'),
            'requester': request.get('requester') or 'không rõ',
        }
    )


def claude_command(claude_bin, prompt):
    """Dòng lệnh chạy Claude không tương tác, chỉ với các tool được phép."""
    return [claude_bin, '-p', prompt, '--permission-mode', 'default',
            '--allowed-tools', *ALLOWED_TOOLS]


def find_claude():
    """Đường dẫn claude.exe: biến môi trường -> PATH -> bản đi kèm extension VSCode."""
    explicit = os.environ.get('CLAUDE_BIN')
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which('claude')
    if found:
        return found
    pattern = str(Path.home() / '.vscode' / 'extensions' / 'anthropic.claude-code-*'
                  / 'resources' / 'native-binary' / 'claude*')
    candidates = sorted(glob.glob(pattern))
    return candidates[-1] if candidates else None


def websocket_url(base_url):
    """https://host -> wss://host/websocket (http -> ws)."""
    return base_url.replace('https://', 'wss://').replace('http://', 'ws://') + '/websocket'


# ----------------------------------------------------------------------
# Nối với Odoo
# ----------------------------------------------------------------------
def odoo_session_cookie(base_url):
    """Đăng nhập tài khoản worker, trả về cookie phiên để mở websocket.

    Websocket của Odoo nhận diện người dùng bằng cookie phiên; không có nó thì kênh riêng
    của tài khoản worker không được đăng ký và Odoo chẳng đẩy gì xuống.
    """
    db = os.environ.get('VTRACKING_DB')
    login = os.environ.get('VTRACKING_WORKER_LOGIN')
    password = os.environ.get('VTRACKING_WORKER_PASSWORD')
    if not (db and login and password):
        vt.fail('Chưa đặt VTRACKING_DB / VTRACKING_WORKER_LOGIN / VTRACKING_WORKER_PASSWORD.')
    payload = json.dumps({
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'db': db, 'login': login, 'password': password},
    }).encode('utf-8')
    request = urllib.request.Request(
        base_url + '/web/session/authenticate', data=payload, method='POST',
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode('utf-8'))
        cookies = response.headers.get_all('Set-Cookie') or []
    if body.get('error') or not (body.get('result') or {}).get('uid'):
        vt.fail('Đăng nhập Odoo thất bại: %s' % (body.get('error') or body))
    for cookie in cookies:
        if cookie.startswith('session_id='):
            return cookie.split(';')[0]
    vt.fail('Đăng nhập được nhưng Odoo không trả cookie phiên.')
    return None


def process_request(request_id, claude_bin, worker_name):
    """Một yêu cầu: nhận việc -> để Claude làm -> kiểm đã trả lời chưa.

    Gọi lại cùng một id nhiều lần là bình thường (bus gửi lại, cron nhắc). Chính lời gọi
    ``claim`` là chỗ chặn xử lý trùng, nên ở đây không cần nhớ gì giữa các lần.
    """
    try:
        request = vt.call('GET', 'requests/%s' % request_id)
    except SystemExit:
        _logger.warning('Không đọc được yêu cầu #%s', request_id)
        return False
    if request['state'] != 'pending':
        _logger.info('Bỏ qua #%s: đang ở trạng thái %s', request_id, request['state'])
        return False
    if not vt.call('POST', 'requests/%s/claim' % request_id, {'worker': worker_name})['claimed']:
        _logger.info('Bỏ qua #%s: máy khác đã nhận', request_id)
        return False

    _logger.info('Bắt đầu #%s (%s)', request_id, request.get('request_type'))
    result = _run_claude(claude_bin, prompt_for(request))
    answered = vt.call('GET', 'requests/%s' % request_id)['state'] != 'processing'
    if answered:
        _logger.info('Xong #%s', request_id)
        return True
    error = result or 'Claude chạy xong nhưng không gọi answer.'
    vt.call('POST', 'requests/%s/fail' % request_id, {'error': error})
    _logger.error('Hỏng #%s: %s', request_id, error)
    return False


def _run_claude(claude_bin, prompt):
    """Chạy Claude. Trả về None nếu chạy trót lọt, hoặc chuỗi mô tả lỗi."""
    environment = dict(os.environ)
    # Máy này có "python" là bản giả của Microsoft Store; đẩy thư mục Python thật lên đầu
    # PATH để lệnh trong skill chạy được dù viết "python" hay "py".
    environment['PATH'] = str(Path(sys.executable).parent) + os.pathsep + environment.get('PATH', '')
    try:
        completed = subprocess.run(
            claude_command(claude_bin, prompt), cwd=str(REPO_ROOT), env=environment,
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=CLAUDE_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return 'Claude chạy quá %s giây, đã dừng.' % CLAUDE_TIMEOUT
    except OSError as exc:
        return 'Không chạy được Claude: %s' % exc
    if completed.returncode != 0:
        return 'Claude thoát với mã %s: %s' % (completed.returncode,
                                               (completed.stderr or '')[-500:])
    return None


def sweep_pending(claude_bin, worker_name, limit=20):
    """Xử lý mọi yêu cầu đang chờ. Chạy lúc khởi động và mỗi lần nối lại websocket —
    đây là thứ bù cho những tin bus gửi lúc máy đang tắt."""
    pending = vt.call('GET', 'requests?state=pending&limit=%s' % limit)['requests']
    for request in pending:
        process_request(request['id'], claude_bin, worker_name)
    return len(pending)


async def listen(claude_bin, worker_name):
    """Giữ websocket và xử lý yêu cầu tới. Rớt thì nối lại với thời gian chờ tăng dần."""
    import websockets  # nhập ở đây để lệnh --once chạy được khi chưa cài thư viện

    base, _ = vt.config()
    url = websocket_url(base)
    delay, last_id = RECONNECT_MIN, 0
    while True:
        try:
            cookie = odoo_session_cookie(base)
            async with websockets.connect(
                url, additional_headers={'Cookie': cookie, 'Origin': base},
                ping_interval=20, ping_timeout=20, max_size=2 ** 20,
            ) as socket_:
                await socket_.send(json.dumps({
                    'event_name': 'subscribe', 'data': {'channels': [], 'last': last_id},
                }))
                _logger.info('Đã nối Odoo, đang chờ yêu cầu.')
                delay = RECONNECT_MIN
                await asyncio.to_thread(sweep_pending, claude_bin, worker_name)
                async for raw in socket_:
                    ids, last = request_ids_from_frame(raw)
                    last_id = max(last_id, last)
                    for request_id in ids:
                        await asyncio.to_thread(process_request, request_id, claude_bin,
                                                worker_name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — worker phải sống sót qua mọi sự cố mạng
            _logger.warning('Mất kết nối (%s). Thử lại sau %ss.', exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX)


def setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()],
    )


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    setup_logging()
    claude_bin = find_claude()
    if not claude_bin:
        vt.fail('Không tìm thấy claude.exe. Đặt biến CLAUDE_BIN trỏ tới nó.')
    worker_name = socket.gethostname()
    _logger.info('Worker "%s" dùng %s', worker_name, claude_bin)

    if '--once' in argv:
        count = sweep_pending(claude_bin, worker_name)
        _logger.info('Đã quét %s yêu cầu đang chờ.', count)
        return 0
    try:
        asyncio.run(listen(claude_bin, worker_name))
    except KeyboardInterrupt:
        _logger.info('Dừng theo yêu cầu.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
