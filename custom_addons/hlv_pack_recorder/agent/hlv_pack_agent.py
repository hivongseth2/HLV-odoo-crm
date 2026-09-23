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
import os
import signal
import subprocess
import sys
import tempfile
import time

import requests
import yaml

AGENT_VERSION = '1.0.0'
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
            stderr=subprocess.PIPE,
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
            self.report_failure(recording_id,
                                "ffmpeg không ghi được gì: %s" % recorder.stderr_tail())
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


def _list_dshow_devices(ffmpeg_bin):
    """In danh sách webcam USB mà Windows đang thấy.

    ffmpeg trả về mã lỗi 1 cho lệnh này kể cả khi thành công (nó coi 'dummy' là
    input hỏng), nên phải đọc stderr chứ đừng nhìn mã thoát.
    """
    proc = subprocess.run(
        [ffmpeg_bin, '-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'],
        capture_output=True, text=True, errors='replace',
    )
    output = proc.stderr or ''
    print("Thiết bị DirectShow Windows đang thấy:")
    print(output)
    print("Chép đúng tên trong dấu nháy vào mục 'device' của camera type: usb.")
    return 0


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

    # Console Windows mặc định cp1252 nên log tiếng Việt ra một đống ký tự escape.
    # Ép UTF-8 để người trực kho đọc được log mà không phải đoán.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            pass

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )

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

    agent = Agent(cfg)
    signal.signal(signal.SIGINT, agent.request_stop)
    signal.signal(signal.SIGTERM, agent.request_stop)
    agent.run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
