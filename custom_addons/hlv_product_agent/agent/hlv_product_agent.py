#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent trợ lý tạo mã hàng, chạy trên máy có Claude Code.

Vòng lặp: hỏi Odoo có tin sale nào chờ -> chạy `claude -p` (nối tiếp phiên cũ của cuộc
hội thoại đó) -> gửi câu trả lời về Odoo -> lặp lại.

Chỉ gọi RA Odoo, không mở cổng nào. Tool MISA Claude gọi đi qua misa_mcp_server.py rồi
lên Odoo: tài khoản MISA không bao giờ nằm trên máy này.

Claude chạy ở chế độ khoá chặt: không shell, không sửa file, chỉ đọc được file trong
thư mục của đúng cuộc hội thoại (ảnh sale gửi), chỉ dùng tool MISA + WebSearch. Sale gõ
gì vào khung chat cũng không đụng được tới máy này.

Chạy:  python hlv_product_agent.py --config agent.yaml
Phụ thuộc:  requests, PyYAML, Claude Code đã đăng nhập.
"""
import argparse
import glob
import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests
import yaml

AGENT_VERSION = '1.1.0'
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = os.path.join(AGENT_DIR, 'misa_mcp_server.py')

# Chạy bằng pythonw.exe thì agent không có console, nhưng tiến trình claude con vẫn
# tự bung cửa sổ đen nếu không chặn.
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
HTTP_TIMEOUT = 30
REPLY_RETRIES = 3

MISA_TOOL_NAMES = [
    'search_product_misa', 'create_product_misa', 'update_product_misa',
    'get_category_info', 'search_category_misa',
]
# Built-in tool Claude được có. Không có Bash/Edit/Write: tin của sale là dữ liệu
# người ngoài gõ, không được biến thành lệnh chạy trên máy này.
BUILTIN_TOOLS = ['Read', 'WebSearch']

DEFAULTS = {
    'model': 'sonnet',
    'work_dir': 'C:/hlv_product_agent',
    'max_parallel': 2,
    'poll_seconds': 3,
    'turn_timeout_seconds': 300,
    'claude_path': '',
}

log = logging.getLogger('hlv_product_agent')


# =============================================================================
# Hàm thuần: dựng tham số, đọc kết quả
# =============================================================================
def build_mcp_config(python_bin, server_path):
    """Chuỗi JSON cho --mcp-config. Không chứa token: token đi qua biến môi trường."""
    return json.dumps({'mcpServers': {'misa': {'command': python_bin, 'args': [server_path]}}})


def build_claude_args(claude_bin, system_prompt_file, mcp_config, model,
                      resume_id=None, new_session_id=None):
    """Dòng lệnh `claude -p` cho một lượt. Đúng một trong resume_id / new_session_id."""
    allowed = ['mcp__misa__%s' % name for name in MISA_TOOL_NAMES] + BUILTIN_TOOLS
    args = [
        claude_bin, '-p',
        '--output-format', 'json',
        '--model', model,
        '--system-prompt-file', system_prompt_file,
        # --restricted: bỏ settings/hook của người dùng máy này, và giam Read trong
        # thư mục làm việc (thư mục riêng của cuộc hội thoại).
        '--restricted',
        '--tools', ','.join(BUILTIN_TOOLS),
        '--strict-mcp-config', '--mcp-config', mcp_config,
        '--allowedTools', ','.join(allowed),
        # Cái gì không nằm trong allowedTools thì từ chối luôn, không có ai ngồi duyệt.
        '--permission-mode', 'dontAsk',
        '--disable-slash-commands',
    ]
    if resume_id:
        args += ['--resume', resume_id]
    else:
        args += ['--session-id', new_session_id]
    return args


def parse_claude_output(stdout):
    """Đọc JSON `--output-format json`.

    Trả: dict ``{'reply', 'session_id', 'error'}``.
    Biên: stdout rỗng / không phải JSON -> reply rỗng, có error.
    """
    try:
        data = json.loads(stdout or '')
    except ValueError:
        return {'reply': '', 'session_id': None, 'error': 'Claude không trả JSON hợp lệ'}
    if not isinstance(data, dict):
        return {'reply': '', 'session_id': None, 'error': 'Claude trả dữ liệu lạ'}
    reply = data.get('result') if isinstance(data.get('result'), str) else ''
    error = None
    if data.get('is_error') or data.get('subtype') not in (None, 'success'):
        error = 'Claude dừng giữa chừng (%s)' % (data.get('subtype') or 'lỗi')
    return {'reply': reply.strip(), 'session_id': data.get('session_id'), 'error': error}


def is_missing_session_error(stderr):
    """Claude báo không tìm thấy phiên để --resume (bị xoá, hoặc máy khác)."""
    return 'No conversation found' in (stderr or '')


# =============================================================================
# Tìm Claude
# =============================================================================
def find_claude(configured=''):
    """Đường dẫn claude.exe. Tìm lại mỗi lượt vì extension VS Code tự cập nhật sẽ đổi
    thư mục, bản cũ bị xoá."""
    if configured:
        return configured
    found = shutil.which('claude')
    if found:
        return found
    home = os.path.expanduser('~')
    native = os.path.join(home, '.local', 'bin', 'claude.exe' if os.name == 'nt' else 'claude')
    if os.path.exists(native):
        return native
    bundled = glob.glob(os.path.join(
        home, '.vscode', 'extensions', 'anthropic.claude-code-*', 'resources', 'native-binary', 'claude*'))
    if bundled:
        return max(bundled, key=os.path.getmtime)
    raise FileNotFoundError('Không tìm thấy Claude Code. Khai claude_path trong agent.yaml.')


def console_python():
    """python.exe cho MCP server: pythonw.exe không có stdio chuẩn nếu không được nối ống."""
    exe = sys.executable
    if exe.lower().endswith('pythonw.exe'):
        candidate = exe[:-len('pythonw.exe')] + 'python.exe'
        if os.path.exists(candidate):
            return candidate
    return exe


# =============================================================================
# Odoo
# =============================================================================
class OdooClient:
    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token
        self.http = requests.Session()

    def call(self, path, **params):
        """Gọi một route type='json'. Trả `result`, raise nếu lỗi mạng / Odoo lỗi."""
        params['token'] = self.token
        response = self.http.post(
            self.url + path,
            json={'jsonrpc': '2.0', 'method': 'call', 'params': params},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if data.get('error'):
            raise RuntimeError('Odoo lỗi: %s' % data['error'].get('message'))
        return data.get('result') or {}

    def download_attachment(self, claim_token, attachment_id):
        response = self.http.post(
            self.url + '/product_agent/agent/attachment',
            data={'token': self.token, 'claim_token': claim_token, 'attachment_id': attachment_id},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.content


# =============================================================================
# Agent
# =============================================================================
class Agent:
    def __init__(self, config):
        self.config = config
        self.odoo = OdooClient(config['odoo_url'], config['token'])
        self.work_dir = os.path.abspath(config['work_dir'])
        os.makedirs(os.path.join(self.work_dir, 'sessions'), exist_ok=True)
        self.system_prompt_file = os.path.join(self.work_dir, 'system_prompt.built.md')
        self.mcp_config = build_mcp_config(console_python(), MCP_SERVER)
        self.pool = ThreadPoolExecutor(max_workers=int(config['max_parallel']))
        self.running = 0
        self.lock = threading.Lock()
        self.stopping = False
        # Vân tay prompt đang nằm trong system_prompt_file. None = chưa có prompt dùng
        # được thì KHÔNG nhận việc: chạy Claude thiếu quy tắc là tạo mã sai.
        self.prompt_version = None

    def refresh_system_prompt(self, wanted_version=None):
        """Tải prompt từ Odoo nếu Odoo báo phiên bản khác bản đang có.

        Prompt sửa trên Odoo (Trợ lý tạo mã hàng > Prompt trợ lý / Quy tắc riêng theo dòng
        hàng). Phiên Claude đang dở vẫn giữ prompt cũ vì Claude ghi lại prompt lúc mở phiên.
        Trả: True nếu đang có prompt dùng được (mới tải hoặc bản cũ còn đó).
        """
        if self.prompt_version and wanted_version == self.prompt_version:
            return True
        try:
            result = self.odoo.call('/product_agent/agent/prompt')
            if not result.get('ok') or not result.get('content'):
                raise RuntimeError(result.get('error') or 'prompt rỗng')
            # Ghi ra file tạm rồi thay: lượt Claude đang khởi động không bao giờ đọc phải
            # file ghi dở. Thay không được (file đang bị đọc) thì giữ bản cũ, poll sau thử lại.
            tmp_path = self.system_prompt_file + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as handle:
                handle.write(result['content'])
            os.replace(tmp_path, self.system_prompt_file)
        except Exception as error:
            log.warning('Chưa tải được prompt từ Odoo: %s', error)
            return bool(self.prompt_version)
        log.info('Đã nạp prompt %s (trước đó %s)', result.get('version'), self.prompt_version)
        self.prompt_version = result.get('version')
        return True

    def run_forever(self):
        log.info('Agent %s chạy, Odoo %s, model %s', AGENT_VERSION, self.odoo.url, self.config['model'])
        while not self.stopping:
            try:
                self.poll_once()
            except Exception as error:
                log.warning('Poll lỗi: %s', error)
            time.sleep(float(self.config['poll_seconds']))

    def poll_once(self):
        with self.lock:
            free = int(self.config['max_parallel']) - self.running
        if not self.prompt_version:
            free = 0
        # Vẫn poll khi đang bận hết: Odoo dựa vào nhịp poll để biết máy còn sống.
        result = self.odoo.call('/product_agent/agent/poll', agent_version=AGENT_VERSION, max_jobs=max(free, 0))
        if not result.get('ok'):
            log.error('Odoo từ chối agent: %s', result.get('error'))
            return
        # Nạp prompt TRƯỚC khi chạy job của chính lần poll này, để tin mới nhận luôn
        # dùng bản prompt Odoo vừa báo.
        self.refresh_system_prompt(result.get('prompt_version'))
        for job in result.get('jobs') or []:
            with self.lock:
                self.running += 1
            self.pool.submit(self.handle_job, job)

    def handle_job(self, job):
        try:
            outcome = self.run_turn(job)
        except Exception as error:
            log.exception('Lượt %s lỗi', job.get('claim_token'))
            outcome = {'reply': '', 'session_id': None, 'error': str(error)[:300]}
        finally:
            with self.lock:
                self.running -= 1
        self.send_reply(job, outcome)

    def run_turn(self, job):
        """Chạy Claude cho một job. Trả dict như parse_claude_output."""
        session_dir = os.path.join(self.work_dir, 'sessions', str(int(job['session_id'])))
        os.makedirs(session_dir, exist_ok=True)
        saved = self.save_attachments(job, session_dir)
        try:
            resume_id = job.get('claude_session_id') or None
            if resume_id:
                outcome, stderr = self.run_claude(job, job['prompt'], session_dir, resume_id=resume_id)
                if not is_missing_session_error(stderr):
                    return outcome
                log.info('Phiên Claude %s không còn, dựng lại ngữ cảnh', resume_id)
            outcome, _stderr = self.run_claude(job, job['prompt_cold'], session_dir)
            return outcome
        finally:
            # Ảnh đã nằm trong ngữ cảnh của phiên Claude; không giữ ảnh khách trên máy.
            for path in saved:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def save_attachments(self, job, session_dir):
        saved = []
        for item in job.get('attachments') or []:
            # Tên do Odoo đặt theo mẫu anh_<id>.<đuôi>; basename để chắc không thoát thư mục.
            path = os.path.join(session_dir, os.path.basename(item['filename']))
            with open(path, 'wb') as handle:
                handle.write(self.odoo.download_attachment(job['claim_token'], item['id']))
            saved.append(path)
        return saved

    def run_claude(self, job, prompt, cwd, resume_id=None):
        """Một lần chạy `claude -p`. Trả (outcome, stderr)."""
        new_session_id = None if resume_id else str(uuid.uuid4())
        args = build_claude_args(
            find_claude(self.config.get('claude_path')), self.system_prompt_file,
            self.mcp_config, self.config['model'],
            resume_id=resume_id, new_session_id=new_session_id,
        )
        env = dict(
            os.environ,
            HLV_ODOO_URL=self.odoo.url,
            HLV_AGENT_TOKEN=self.odoo.token,
            HLV_CLAIM_TOKEN=job['claim_token'],
            PYTHONIOENCODING='utf-8',
        )
        started = time.time()
        try:
            proc = subprocess.run(
                args, input=prompt, cwd=cwd, env=env, capture_output=True,
                text=True, encoding='utf-8', errors='replace',
                timeout=int(self.config['turn_timeout_seconds']), creationflags=NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            return ({'reply': '', 'session_id': resume_id or new_session_id,
                     'error': 'Claude chạy quá %ss' % self.config['turn_timeout_seconds']}, '')

        outcome = parse_claude_output(proc.stdout)
        # Phiên mới mà Claude chết trước khi in JSON: vẫn nhớ mã phiên đã đặt, vì có thể
        # nó đã kịp ghi lại một phần hội thoại.
        outcome['session_id'] = outcome['session_id'] or resume_id or new_session_id
        if proc.returncode != 0 and not outcome['error']:
            outcome['error'] = (proc.stderr or 'claude thoát mã %s' % proc.returncode).strip()[-300:]
        log.info('Phiên %s lượt %s: %.1fs, rc=%s%s', job['session_id'], job['claim_token'][:8],
                 time.time() - started, proc.returncode,
                 ', lỗi: %s' % outcome['error'] if outcome['error'] else '')
        return outcome, proc.stderr

    def send_reply(self, job, outcome):
        for attempt in range(1, REPLY_RETRIES + 1):
            try:
                self.odoo.call(
                    '/product_agent/agent/reply',
                    claim_token=job['claim_token'],
                    reply=outcome.get('reply') or '',
                    claude_session_id=outcome.get('session_id') or '',
                    error=outcome.get('error') or '',
                )
                return
            except Exception as error:
                log.warning('Gửi trả lời lần %s lỗi: %s', attempt, error)
                time.sleep(2 * attempt)
        # Odoo sẽ tự thả lượt này sau CLAIM_TIMEOUT và báo sale gửi lại.
        log.error('Bỏ trả lời lượt %s sau %s lần thử', job['claim_token'], REPLY_RETRIES)

    def stop(self):
        self.stopping = True
        self.pool.shutdown(wait=True)


# =============================================================================
# Khởi động
# =============================================================================
def load_config(path):
    """Đọc agent.yaml, bù giá trị mặc định. Raise ValueError nếu thiếu odoo_url / token."""
    with open(path, encoding='utf-8') as handle:
        raw = yaml.safe_load(handle) or {}
    config = dict(DEFAULTS)
    config.update({key: value for key, value in raw.items() if value not in (None, '')})
    for key in ('odoo_url', 'token'):
        if not config.get(key):
            raise ValueError('agent.yaml thiếu %s' % key)
    return config


def setup_logging(work_dir):
    os.makedirs(work_dir, exist_ok=True)
    log.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(work_dir, 'agent.log'), maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8')
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)
    # pythonw.exe không có stderr.
    if sys.stderr:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        log.addHandler(stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--config', default=os.path.join(AGENT_DIR, 'agent.yaml'))
    parser.add_argument('--check', action='store_true',
                        help='Kiểm cấu hình, Claude và kết nối Odoo rồi thoát.')
    options = parser.parse_args()

    config = load_config(options.config)
    setup_logging(config['work_dir'])
    agent = Agent(config)

    if options.check:
        print('Claude:', find_claude(config.get('claude_path')))
        result = agent.odoo.call('/product_agent/agent/poll', agent_version=AGENT_VERSION, max_jobs=0)
        print('Odoo:', 'OK' if result.get('ok') else 'TỪ CHỐI (%s)' % result.get('error'))
        if result.get('ok'):
            loaded = agent.refresh_system_prompt(result.get('prompt_version'))
            print('Prompt:', ('%s (%s)' % (agent.system_prompt_file, agent.prompt_version))
                  if loaded else 'LOI - khong tai duoc prompt tu Odoo')
        return

    try:
        agent.run_forever()
    except KeyboardInterrupt:
        log.info('Dừng agent, đợi các lượt đang chạy xong...')
        agent.stop()


if __name__ == '__main__':
    main()
