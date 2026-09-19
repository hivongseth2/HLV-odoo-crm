#!/usr/bin/env python3
"""Lớp gọi API V-Tracking — MỘT file duy nhất biết chuyện "gọi bằng cách nào".

Vì sao tách riêng: quy trình điều phối (SKILL.md) không được dính vào chuyện HTTP, header
hay khoá. Sau này đổi chỗ chạy thì chỉ file này đổi:

  * Chạy từ máy người dùng (hôm nay)  -> giữ nguyên
  * Chạy từ tiến trình trên server     -> giữ nguyên, chỉ đổi biến môi trường
  * Chạy trong Odoo (server action)    -> thay file này bằng lớp gọi ORM, SKILL.md không đổi

Chỉ dùng thư viện chuẩn: máy nào có Python là chạy được, không cần cài thêm.

Dùng (BỎ dấu / đầu khi chạy trên Git Bash ở Windows — xem ghi chú cuối file):
    python vt.py get  context
    python vt.py get  "orders/pending?limit=20&unplanned_only=1"
    python vt.py post plans/12/notes '{"reasoning": "..."}'
    python vt.py post plans/12/notes @note.json

Biến môi trường:
    VTRACKING_BASE_URL   ví dụ https://hoanglongvu-staging-v2-xxxx.dev.odoo.com
    VTRACKING_API_KEY    khoá tạo ở V-Tracking > Cấu hình > Khoá API
    VTRACKING_INSECURE   đặt 1 để bỏ qua kiểm chứng chỉ (chỉ dùng khi thật sự cần)

Thoát 0 khi thành công, 1 khi API trả lỗi, 2 khi cấu hình/tham số/kết nối sai.

GHI CHÚ WINDOWS: Git Bash tự đổi tham số bắt đầu bằng "/" thành đường dẫn Windows —
"/context" biến thành "C:/Program Files/Git/context" trước cả khi Python thấy nó. Nên viết
đường dẫn KHÔNG có dấu / đầu; script tự thêm vào.
"""

import http.client
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

PREFIX = '/api/v1/ai'
# Đầu đường dẫn Windows: ổ đĩa một chữ cái rồi ':/' hoặc ':\\'. Khớp CHẶT như vậy để
# một query string có dấu hai chấm không bị cắt nhầm thành "đường dẫn file".
DRIVE_PREFIX = re.compile(r'^[A-Za-z]:[/\\\\]')
TIMEOUT = 60


def fail(message, code=2):
    print('LỖI: %s' % message, file=sys.stderr)
    raise SystemExit(code)


def config():
    base = (os.environ.get('VTRACKING_BASE_URL') or '').rstrip('/')
    key = os.environ.get('VTRACKING_API_KEY') or ''
    if not base or not key:
        fail('Chưa đặt VTRACKING_BASE_URL và/hoặc VTRACKING_API_KEY. '
             'Xem references/setup.md.')
    return base, key


def read_body(argument):
    """Body JSON từ tham số dòng lệnh, hoặc từ file khi bắt đầu bằng @."""
    if not argument:
        return {}
    raw = argument
    if argument.startswith('@'):
        try:
            with open(argument[1:], encoding='utf-8') as handle:
                raw = handle.read()
        except OSError as exc:
            fail('Không đọc được file body: %s' % exc)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        fail('Body không phải JSON hợp lệ: %s' % exc)


def http_error_message(exc):
    """Thông điệp đọc được từ một HTTPError.

    API luôn trả JSON kể cả khi lỗi, nên đọc phần ``error`` ra để hiện đúng lý do nghiệp vụ
    thay vì chỉ hiện "HTTP 422".
    """
    raw = exc.read().decode('utf-8', 'replace')
    try:
        error = json.loads(raw)['error']
    except (ValueError, KeyError, TypeError):
        return 'HTTP %s: %s' % (exc.code, raw[:500])
    return '%s (HTTP %s): %s' % (error.get('code', '?'), exc.code, error.get('message', ''))


def normalize_path(path):
    """Đường dẫn người gõ -> đường dẫn API.

    Nhận cả "context", "/context" và "/api/v1/ai/context". Cắt phần Git Bash chèn vào khi
    nó tưởng "/context" là đường dẫn file: giữ lại từ "/api/v1/ai" nếu thấy, không thì lấy
    đoạn cuối.
    """
    if PREFIX in path:
        return path[path.index(PREFIX):]
    if DRIVE_PREFIX.match(path):
        # "C:/Program Files/Git/context" -> "context"
        path = path.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]
    return PREFIX + '/' + path.lstrip('/')


def call(method, path, body=None):
    """Gọi một endpoint. Trả về phần ``data``; ném SystemExit khi API báo lỗi."""
    base, key = config()
    path = normalize_path(path)
    url = base + path

    data = json.dumps(body).encode('utf-8') if body is not None and method == 'POST' else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header('X-API-Key', key)
    request.add_header('Content-Type', 'application/json')

    context = None
    if os.environ.get('VTRACKING_INSECURE') == '1':
        context = ssl._create_unverified_context()  # noqa: S323 — có chủ đích, phải khai báo

    # Lỗi được gom về một biến rồi mới báo SAU khối except: ném SystemExit ngay trong
    # except thì Python nối chuỗi ngoại lệ và in ra traceback thừa, che mất thông điệp thật.
    payload, problem, code = None, None, 1
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        problem = http_error_message(exc)
    except urllib.error.URLError as exc:
        # Không kết nối được là chuyện cấu hình/mạng, không phải API từ chối -> mã 2.
        problem, code = 'Không kết nối được %s: %s' % (url, exc.reason), 2
    except (ValueError, OSError, http.client.HTTPException) as exc:
        # InvalidURL nằm ở nhánh này: Git Bash đổi "/context" thành đường dẫn Windows và
        # nhét cả khoảng trắng vào URL. Bắt lại để báo cho ra lẽ thay vì đổ traceback.
        problem, code = 'Yêu cầu không hợp lệ (%s): %s' % (type(exc).__name__, exc), 2
    if problem:
        fail(problem, code)

    if not payload.get('success'):
        error = payload.get('error') or {}
        fail('%s: %s' % (error.get('code', '?'), error.get('message', payload)), 1)
    return payload.get('data')


def main(argv):
    if len(argv) < 3 or argv[1].lower() not in ('get', 'post'):
        fail('Dùng: vt.py get|post <đường dẫn> [body JSON hoặc @file]')
    method = argv[1].upper()
    body = read_body(argv[3]) if method == 'POST' and len(argv) > 3 else (
        {} if method == 'POST' else None
    )
    result = call(method, argv[2], body)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
