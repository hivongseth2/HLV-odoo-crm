#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent ghi hình đóng gói, chạy trên máy tại kho.

Vòng lặp: hỏi Odoo có lệnh gì -> chạy/dừng ffmpeg -> gửi file lên -> lặp lại.

Chỉ gọi RA Odoo, không mở cổng nào. Không có gì lắng nghe nên không cần lo
firewall, mixed content hay trang web lạ gọi vào.

URL RTSP nằm trong file cấu hình cạnh script này, KHÔNG nằm trên Odoo. Odoo chỉ
gửi mã camera; agent tự tra ra URL. Token Odoo rò ra ngoài cũng không lộ camera.

Chạy:  python hlv_pack_agent.py --config agent.yaml
Phụ thuộc:  requests, PyYAML, và ffmpeg có trong PATH.
"""
import argparse
import logging
import logging.handlers
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

import requests
import yaml

AGENT_VERSION = '1.1.0'

# Chay bang pythonw.exe thi agent khong co console, nhung moi tien trinh ffmpeg
# con van tu bung mot cua so den neu khong chan. Nhan vien thay cua so la tat.
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
POLL_SECONDS = 2
CHUNK_BYTES = 4 * 1024 * 1024
UPLOAD_RETRIES = 3

log = logging.getLogger('hlv_pack_agent')

# Webcam USB không tự đóng dấu giờ lên hình như camera IP, mà nó vốn đã phải nén
# lại rồi nên thêm chữ gần như miễn phí. Dùng %{localtime} dạng mặc định thay vì
# tự khai định dạng: khai định dạng phải escape dấu hai chấm nhiều tầng, rất dễ
# sai mà chỉ phát hiện ra lúc đang quay thật.
TIME_OVERLAY = (
    "drawtext=fontfile={font}:text='%{{localtime}}'"
    ":fontcolor=white:fontsize=28:box=1:boxcolor=black@0.5:boxborderw=8"
    ":x=16:y=h-th-16"
)
# Dấu hai chấm sau tên ổ đĩa phải escape BẰNG HAI BACKSLASH: bộ phân tích
# filter của ffmpeg bóc hai tầng, một backslash bị ăn mất ở tầng đầu và
# ffmpeg cắt chuỗi ngay dấu hai chấm -> "No option name near ...".
DEFAULT_FONT = r'C\\:/Windows/Fonts/arial.ttf'


def build_ffmpeg_args(camera, out_path, max_seconds, ffmpeg_bin='ffmpeg'):
    """Dựng dòng lệnh ffmpeg cho một camera.

    camera: chuỗi URL RTSP (dạng ngắn), hoặc dict có 'type':
        'rtsp' (mặc định) — camera IP. Chép thẳng luồng đã nén bằng -c copy:
            không giải mã, không nén lại, chất lượng đúng bản gốc, CPU ~0.
        'usb' — webcam cắm dây qua DirectShow. Webcam hầu như không bao giờ xuất
            H.264, nên BẮT BUỘC phải nén lại; đổi lại đóng được dấu giờ lên hình.
    out_path: file đích.
    max_seconds: trần thời gian, phòng khi lệnh dừng không tới được.

    Trả về: list tham số đầy đủ cho subprocess.
        Biên: thiếu 'url' (rtsp) hoặc 'device' (usb) -> ValueError.
    """
    if isinstance(camera, str):
        camera = {'type': 'rtsp', 'url': camera}
    if not isinstance(camera, dict):
        raise ValueError('cấu hình camera phải là chuỗi URL hoặc dict')

    kind = (camera.get('type') or 'rtsp').lower()
    args = [ffmpeg_bin, '-hide_banner', '-loglevel', 'warning']

    if kind == 'rtsp':
        url = camera.get('url')
        if not url:
            raise ValueError("camera rtsp thiếu 'url'")
        # -rtsp_transport tcp: UDP mất gói là vỡ hình, mà bằng chứng thì không
        # được phép vỡ.
        args += ['-rtsp_transport', 'tcp', '-i', url, '-c', 'copy']

    elif kind == 'usb':
        device = camera.get('device')
        if not device:
            raise ValueError("camera usb thiếu 'device' (tên thiết bị DirectShow)")
        size = camera.get('size') or '1280x720'
        fps = str(camera.get('fps') or 24)
        bitrate = camera.get('bitrate') or '4M'
        # -rtbufsize: webcam đẩy frame chưa nén rất nặng, buffer nhỏ là rớt khung.
        args += [
            '-f', 'dshow', '-rtbufsize', '256M',
            '-video_size', size, '-framerate', fps,
            '-i', 'video=%s' % device,
        ]
        if camera.get('overlay_time', True):
            font = camera.get('font') or DEFAULT_FONT
            args += ['-vf', TIME_OVERLAY.format(font=font)]
        args += [
            '-c:v', 'libx264', '-preset', 'veryfast', '-b:v', bitrate,
            '-pix_fmt', 'yuv420p',
        ]

    else:
        raise ValueError("type camera lạ: %s" % kind)

    args += ['-t', str(max_seconds), '-movflags', '+faststart', '-y', out_path]
    return args


class Recorder:
    """Một tiến trình ffmpeg đang ghi một camera."""

    def __init__(self, recording_id, camera_code, camera_cfg, out_path, max_seconds, ffmpeg_bin='ffmpeg'):
        self.recording_id = recording_id
        self.camera_code = camera_code
        self.out_path = out_path
        cmd = build_ffmpeg_args(camera_cfg, out_path, max_seconds, ffmpeg_bin)
        log.info("ffmpeg start rec=%s cam=%s -> %s", recording_id, camera_code, out_path)
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, creationflags=NO_WINDOW,
        )

    def is_running(self):
        return self.proc.poll() is None

    def stop(self, timeout=15):
        """Dừng êm để ffmpeg kịp đóng file mp4 cho tử tế.

        Gửi 'q' vào stdin là cách ffmpeg tự kết thúc và ghi moov atom. Giết thẳng
        bằng kill sẽ để lại file mp4 không mở được.
        """
        if not self.is_running():
            return
        try:
            self.proc.stdin.write(b'q')
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning("ffmpeg rec=%s không tự thoát, phải kill", self.recording_id)
            self.proc.kill()
            self.proc.wait(timeout=5)

    def stderr_tail(self, limit=400):
        try:
            data = self.proc.stderr.read() or b''
        except (OSError, ValueError):
            return ''
        return data.decode('utf-8', 'replace')[-limit:]


class Agent:

    def __init__(self, cfg):
        self.base_url = cfg['odoo_url'].rstrip('/')
        self.station_key = cfg['station_key']
        self.token = cfg['token']
        # Ép khoá về chuỗi: mã camera kiểu "0001" không có nháy sẽ được YAML đọc
        # thành số 1, tra theo mã Odoo gửi xuống sẽ không khớp.
        self.cameras = {str(k): v for k, v in (cfg.get('cameras') or {}).items()}
        self.ffmpeg_bin = cfg.get('ffmpeg_path') or 'ffmpeg'
        self.work_dir = cfg.get('work_dir') or os.path.join(tempfile.gettempdir(), 'hlv_pack_rec')
        os.makedirs(self.work_dir, exist_ok=True)
        self.session = requests.Session()
        self.active = {}  # recording_id -> Recorder
        self.running = True

    # ---------------- giao tiếp Odoo ----------------
    def _call_json(self, path, payload, timeout=20):
        """Gọi route type='json' của Odoo (bọc trong jsonrpc envelope).

        Trả về dict kết quả, hoặc None nếu gọi hỏng — bên gọi tự quyết định thử lại.
        """
        body = {'jsonrpc': '2.0', 'method': 'call', 'params': dict(
            payload, station_key=self.station_key, token=self.token)}
        try:
            resp = self.session.post(self.base_url + path, json=body, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("gọi %s hỏng: %s", path, exc)
            return None
        if 'error' in data:
            log.error("Odoo báo lỗi ở %s: %s", path, data['error'])
            return None
        return data.get('result') or {}

    def poll(self):
        return self._call_json('/pack_agent/poll', {
            'active_ids': [rid for rid, r in self.active.items() if r.is_running()],
            'agent_version': AGENT_VERSION,
        })

    def report_failure(self, recording_id, reason):
        log.error("rec=%s hỏng: %s", recording_id, reason)
        self._call_json('/pack_agent/report_failure', {
            'recording_id': recording_id, 'reason': reason,
        })

    # ---------------- xử lý lệnh ----------------
    def handle(self, command):
        action = command.get('action')
        recording_id = command.get('recording_id')
        if action == 'start':
            self.start_recording(command)
        elif action == 'stop':
            self.stop_recording(recording_id)
        else:
            log.warning("lệnh lạ: %s", command)

    def start_recording(self, command):
        recording_id = command['recording_id']
        code = command.get('camera_code')
        if recording_id in self.active:
            return  # đã chạy rồi, poll lặp lại lệnh cũ

        camera_cfg = self.cameras.get(str(code))
        if not camera_cfg:
            self.report_failure(recording_id, "agent chưa khai camera mã '%s' trong file cấu hình" % code)
            return

        label = command.get('label') or ('rec%s' % recording_id)
        out_path = os.path.join(self.work_dir, '%s_%d.mp4' % (_safe(label), recording_id))
        try:
            self.active[recording_id] = Recorder(
                recording_id, code, camera_cfg, out_path,
                int(command.get('max_seconds') or 1800),
                ffmpeg_bin=self.ffmpeg_bin,
            )
        except ValueError as exc:
            self.report_failure(recording_id, "cấu hình camera '%s' sai: %s" % (code, exc))
        except FileNotFoundError:
            self.report_failure(recording_id, "không chạy được ffmpeg: %s" % self.ffmpeg_bin)
        except OSError as exc:
            self.report_failure(recording_id, "không chạy được ffmpeg: %s" % exc)

    def stop_recording(self, recording_id):
        recorder = self.active.pop(recording_id, None)
        if not recorder:
            return
        recorder.stop()
        if not os.path.exists(recorder.out_path) or os.path.getsize(recorder.out_path) < 51200:
            stderr = recorder.stderr_tail()
            hint = explain_ffmpeg_error(stderr)
            self.report_failure(
                recording_id,
                ("ffmpeg không ghi được gì — %s\n\n%s" % (hint, stderr)) if hint
                else ("ffmpeg không ghi được gì: %s" % stderr))
            _remove(recorder.out_path)
            return
        if self.upload(recording_id, recorder.out_path):
            _remove(recorder.out_path)
        else:
            # Giữ file lại để lấy tay, đừng xoá mất bằng chứng vì mạng chập chờn.
            log.error("giữ lại file chưa gửi được: %s", recorder.out_path)

    def sweep_finished(self):
        """ffmpeg chạm trần -t hoặc chết giữa chừng thì tự dọn, không chờ lệnh stop."""
        for recording_id in list(self.active):
            recorder = self.active[recording_id]
            if recorder.is_running():
                continue
            log.info("rec=%s ffmpeg tự kết thúc", recording_id)
            self.stop_recording(recording_id)

    # ---------------- gửi file ----------------
    def upload(self, recording_id, path):
        size = os.path.getsize(path)
        log.info("gửi rec=%s %.1fMB", recording_id, size / 1024 / 1024)
        index = 0
        with open(path, 'rb') as fh:
            while True:
                chunk = fh.read(CHUNK_BYTES)
                if not chunk:
                    break
                if not self._send_chunk(recording_id, index, chunk):
                    return False
                index += 1

        result = self._call_json('/pack_agent/upload_done', {
            'recording_id': recording_id, 'ext': '.mp4',
        }, timeout=120)
        if not result or not result.get('ok'):
            log.error("rec=%s chốt upload hỏng: %s", recording_id, result)
            return False
        log.info("rec=%s gửi xong", recording_id)
        return True

    def _send_chunk(self, recording_id, index, chunk):
        data = {
            'station_key': self.station_key, 'token': self.token,
            'recording_id': str(recording_id), 'index': str(index),
        }
        for attempt in range(1, UPLOAD_RETRIES + 1):
            try:
                resp = self.session.post(
                    self.base_url + '/pack_agent/upload_chunk',
                    data=data, files={'chunk': ('part.bin', chunk)}, timeout=120,
                )
                if resp.status_code == 200:
                    return True
                log.warning("khúc %d bị từ chối HTTP %s", index, resp.status_code)
                if resp.status_code in (403, 404, 413):
                    return False  # sai token / bản ghi lạ / khúc quá to: thử lại vô ích
            except requests.RequestException as exc:
                log.warning("khúc %d lỗi mạng lần %d: %s", index, attempt, exc)
            time.sleep(2 * attempt)
        return False

    # ---------------- vòng lặp ----------------
    def run(self):
        log.info("agent %s khởi động, bàn=%s, %d camera đã khai",
                 AGENT_VERSION, self.station_key, len(self.cameras))
        while self.running:
            try:
                self.sweep_finished()
                result = self.poll()
                if result and result.get('ok'):
                    for command in result.get('commands') or []:
                        self.handle(command)
                elif result is not None:
                    log.error("Odoo từ chối: %s — kiểm lại station_key và token", result.get('error'))
            except Exception:
                log.exception("lỗi không lường trước trong vòng lặp")
            time.sleep(POLL_SECONDS)

        log.info("đang dừng, đóng nốt các file đang ghi")
        for recording_id in list(self.active):
            self.stop_recording(recording_id)

    def request_stop(self, *_args):
        self.running = False


def _run_ffmpeg_text(ffmpeg_bin, args):
    """Chạy ffmpeg và trả stderr dưới dạng text.

    Các lệnh liệt kê thiết bị đều thoát với mã lỗi khác 0 (ffmpeg coi 'dummy' là
    input hỏng) nên phải đọc stderr, đừng nhìn mã thoát.
    """
    proc = subprocess.run(
        [ffmpeg_bin, '-hide_banner'] + args,
        capture_output=True, text=True, errors='replace', creationflags=NO_WINDOW,
    )
    return proc.stderr or ''


def parse_video_devices(listing):
    """Lọc tên webcam từ output -list_devices.

    listing: stderr thô của ffmpeg.
    Trả về: list tên thiết bị video, bỏ thiết bị audio và bỏ dòng
        "Alternative name". Biên: không có webcam nào -> list rỗng.
    """
    names = []
    for line in listing.splitlines():
        if 'Alternative name' in line:
            continue
        match = re.search(r'"([^"]+)"\s*\(video\)', line)
        if match:
            names.append(match.group(1))
    return names


def parse_video_modes(listing):
    """Lọc các chế độ hình từ output -list_options.

    Trả về: list (size, [fps...]) đã gộp trùng, sắp giảm dần theo số pixel.
        ffmpeg in mỗi độ phân giải nhiều lần cho từng pixel_format, và ghi thành
        cặp min/max fps — gộp hết lại cho gọn.
        Biên: không đọc được chế độ nào -> list rỗng.
    """
    modes = {}
    pattern = re.compile(r'min s=(\d+x\d+) fps=([\d.]+) max s=(\d+x\d+) fps=([\d.]+)')
    for line in listing.splitlines():
        m = pattern.search(line)
        if not m:
            continue
        for size, fps in ((m.group(1), m.group(2)), (m.group(3), m.group(4))):
            modes.setdefault(size, set()).add(int(float(fps)))

    def pixels(size):
        w, h = size.split('x')
        return int(w) * int(h)

    return [(size, sorted(fps_set))
            for size, fps_set in sorted(modes.items(), key=lambda kv: -pixels(kv[0]))]


def _setup_logging(args):
    """Ghi log ra file, và ra console nếu có console.

    Chay bang pythonw.exe (khong cua so) thi sys.stdout/stderr deu la None, nen
    log chi con duong ra file. File la cai duy nhat con lai de chan doan khi
    agent chay ngam, vi vay no luon duoc bat.
    """
    log_path = os.path.join(
        os.path.dirname(os.path.abspath(args.config)) or '.', 'agent.log')
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

    # Xoay vong 5MB x 3: du de lan nguoc vai ngay ma khong an het o dia.
    handlers = [logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')]

    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            pass
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)

    # urllib3 ghi mot dong DEBUG cho moi lan poll (2 giay/lan) — day file log day
    # rac trong vai gio ma khong noi them duoc gi.
    logging.getLogger('urllib3').setLevel(logging.INFO)
    return log_path


def _list_dshow_devices(ffmpeg_bin):
    """In webcam Windows đang thấy kèm chế độ hỗ trợ và mẫu YAML điền sẵn."""
    listing = _run_ffmpeg_text(
        ffmpeg_bin, ['-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'])
    devices = parse_video_devices(listing)
    if not devices:
        print("Không thấy webcam nào. Nếu camera của bàn này là camera IP thì")
        print("không dùng lệnh này — khai thẳng URL RTSP vào agent.yaml.")
        return 1

    for device in devices:
        print()
        print('=' * 68)
        print('Webcam: %s' % device)
        modes = parse_video_modes(_run_ffmpeg_text(
            ffmpeg_bin, ['-f', 'dshow', '-list_options', 'true', '-i', 'video=%s' % device]))
        if modes:
            print('  Chế độ hỗ trợ (chỉ được chọn trong danh sách này):')
            for size, fps_list in modes:
                print('    %-12s fps %s' % (size, ', '.join(str(f) for f in fps_list)))
            best_size, best_fps = modes[0][0], modes[0][1][0]
        else:
            print('  Không đọc được chế độ hỗ trợ — thử khai 1280x720 / 15 fps.')
            best_size, best_fps = '1280x720', 15

        print()
        print('  Chép khối này vào mục cameras: trong agent.yaml,')
        print('  đổi "MA_CAMERA" thành đúng Mã camera khai trong Odoo:')
        print()
        print('    "MA_CAMERA":')
        print('      type: usb')
        print('      device: "%s"' % device)
        print('      size: "%s"' % best_size)
        print('      fps: %d' % best_fps)
        print('      bitrate: "3M"')
        print('      overlay_time: true')
    print()
    return 0


# Lỗi ffmpeg hay gặp, kèm nguyên nhân thật sự. Đưa thẳng vào Odoo để người
# trực kho khỏi phải đọc log kỹ thuật rồi đoán.
FFMPEG_HINTS = (
    ('Error during demuxing: I/O error',
     "webcam đang bị ứng dụng khác chiếm (trình duyệt, OBS, Teams, Zoom...). "
     "DirectShow chỉ cho một ứng dụng giữ webcam tại một thời điểm — đóng ứng "
     "dụng kia, hoặc tắt luồng quay bằng trình duyệt."),
    ('Could not run filter',
     "không dựng được bộ lọc đóng dấu giờ — kiểm đường dẫn font trong 'font'."),
    ('Could not set video options',
     "webcam không hỗ trợ size/fps đang khai. Chạy --list-cameras xem nó "
     "hỗ trợ những chế độ nào."),
    ('Connection refused',
     "không kết nối được camera IP — sai IP/cổng, hoặc camera đang tắt."),
    ('401 Unauthorized',
     "sai tài khoản hoặc mật khẩu trong URL RTSP."),
    ('Immediate exit requested',
     "ffmpeg bị dừng ngang trước khi ghi được gì."),
)


def explain_ffmpeg_error(stderr):
    """Dịch lỗi ffmpeg thành câu nói rõ nguyên nhân.

    stderr: chuỗi log ffmpeg.
    Trả về: câu giải thích, hoặc chuỗi rỗng nếu không nhận ra lỗi nào quen —
        khi đó bên gọi cứ gửi nguyên log thô lên, còn hơn là nuốt mất.
    """
    for needle, hint in FFMPEG_HINTS:
        if needle in (stderr or ''):
            return hint
    return ''


def _safe(text):
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in (text or ''))[:80]


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description="Agent ghi video đóng gói HLV")
    parser.add_argument('--config', default='agent.yaml')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--list-cameras', action='store_true',
                        help="Liệt kê tên thiết bị webcam USB để điền vào 'device'")
    args = parser.parse_args()

    _setup_logging(args)

    if not os.path.exists(args.config):
        log.error("không thấy file cấu hình: %s", args.config)
        return 2
    with open(args.config, encoding='utf-8') as fh:
        cfg = yaml.safe_load(fh) or {}

    if args.list_cameras:
        return _list_dshow_devices(cfg.get('ffmpeg_path') or 'ffmpeg')

    missing = [k for k in ('odoo_url', 'station_key', 'token') if not cfg.get(k)]
    if missing:
        log.error("file cấu hình thiếu: %s", ', '.join(missing))
        return 2

    log.info("ghi log vao %s", os.path.join(
        os.path.dirname(os.path.abspath(args.config)) or '.', 'agent.log'))
    agent = Agent(cfg)
    signal.signal(signal.SIGINT, agent.request_stop)
    signal.signal(signal.SIGTERM, agent.request_stop)
    agent.run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
