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
import collections
import logging
import logging.handlers
import os
import re
import queue
import shutil
import signal
import subprocess
import threading
import sys
import tempfile
import time

import requests
import yaml

AGENT_VERSION = '2.3.1'

IS_WINDOWS = os.name == 'nt'

# Chay bang pythonw.exe thi agent khong co console, nhung moi tien trinh ffmpeg
# con van tu bung mot cua so den neu khong chan. Nhan vien thay cua so la tat.
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if IS_WINDOWS else 0

# Camera cam day: Windows doc qua DirectShow theo TEN thiet bi, Linux doc qua
# Video4Linux2 theo DUONG DAN (/dev/videoN). Hai thu khac han nhau nen phai tach.
USB_INPUT_FORMAT = 'dshow' if IS_WINDOWS else 'v4l2'

# Font de dong dau gio len hinh webcam.
# Windows: dau hai cham sau ten o dia phai escape BANG HAI BACKSLASH — bo phan
# tich filter cua ffmpeg boc hai tang, mot backslash bi an mat o tang dau va
# ffmpeg cat chuoi ngay dau hai cham -> "No option name near ...".
# Linux: duong dan khong co dau hai cham nen khong phai escape gi.
DEFAULT_FONT = (r'C\\:/Windows/Fonts/arial.ttf' if IS_WINDOWS
                else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
POLL_SECONDS = 2

# Khuc 2MB chu khong phai 4MB: duong len cua kho hep, khuc to de cham tran thoi
# gian ghi socket ("The write operation timed out" - da gap that voi file 70MB).
# Khuc nho thi moi lan gui ngan hon, hong thi lam lai it hon.
CHUNK_BYTES = 2 * 1024 * 1024
UPLOAD_RETRIES = 5

# So dong stderr cuoi cung giu lai cho moi tien trinh ffmpeg. Chi de bao loi nen
# khong can nhieu; giu nguyen ca phien thi mot camera nhieu se ngon het bo nho.
STDERR_KEEP_LINES = 80

# Cap nhat hong thi cho chung nay giay moi thu lai. Khong co no, mot ban moi
# loi se lam agent tai di tai lai moi 2 giay cho toi khi co nguoi phat hien.
UPDATE_RETRY_SECONDS = 600

# Ban agent phai lon hon nguong nay moi duoc coi la tai du. Ban that ~40KB;
# mot trang loi HTML hay mot lan tai hut deu nho hon nhieu.
MIN_AGENT_BYTES = 10 * 1024

# So lan cho phep chay lai ffmpeg trong MOT ban ghi khi luong RTSP bi dut.
# Co tran vi mot camera hong han se dut lien tuc; chay lai vo han thi chi tao ra
# hang tram doan rac roi van khong co hinh.
# 60 chu khong phai 20: mot phien dong goi dai muoi phut ma mang chop moi ~20
# giay la da can hon 20 lan noi lai. Chay lai vo ich thi ton vai giay moi lan va
# co dong log rieng, con thieu mot lan la mat phan con lai cua phieu.
MAX_SEGMENT_RESTARTS = 60

# Doan ngan hon chung nay coi nhu khong co gi - bo di truoc khi noi, de mot doan
# 0 byte khong lam hong ca file cuoi.
MIN_SEGMENT_BYTES = 64 * 1024

# Quet lai file chua gui duoc moi chung nay giay. Khong quet moi vong poll (2
# giay): mang dang hong ma dong lien tuc chi to lam nghen them.
RETRY_SCAN_SECONDS = 120

# File vua sinh ra co the ffmpeg con dang ghi do. Chi dung toi file da nam yen.
RETRY_MIN_AGE_SECONDS = 60

# --- Day thang len Google Drive ---
# Google doi moi khuc (tru khuc cuoi) la BOI SO CUA 256KB. 2MB = 8 x 256KB:
# du nho de mot lan gui khong qua lau tren duong truyen hep cua kho, du to de
# khong ton qua nhieu lan bat tay.
DRIVE_CHUNK_BYTES = 2 * 1024 * 1024
DRIVE_UPLOAD_URL = ('https://www.googleapis.com/upload/drive/v3/files'
                    '?uploadType=resumable&fields=id,webViewLink,size')
# Phien resumable cua Google song ~1 tuan. Luu URL phien canh file de agent khoi
# dong lai van gui TIEP tu cho dut, thay vi lam lai tu dau.
RESUME_SUFFIX = '.resume'

# Poll thanh cong khong ghi log gi ca — dung, vi 1800 dong moi gio thi khong ai
# doc noi. Nhung luc truy su co, log trong mot khoang lai khong phan biet duoc
# "chay binh thuong" voi "agent khong chay" — dung cau hoi can tra loi nhat.
PULSE_SECONDS = 300

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
        args += ['-rtsp_transport', 'tcp', '-i', url]

        # Hình LUÔN chép nguyên, không nén lại — đó là lý do CPU gần bằng 0.
        args += ['-c:v', 'copy']

        # Tiếng thì khác. Nhiều camera IP phát tiếng dạng G.711 (pcm_mulaw /
        # pcm_alaw) mà container MP4 KHÔNG chứa được, ffmpeg từ chối ghi file
        # ngay từ header: "Could not find tag for codec pcm_mulaw". Đã gặp thật:
        # một bàn hai camera, cái có tiếng chết, cái không tiếng chạy ngon.
        #
        # Mặc định BỎ TIẾNG: bằng chứng đóng gói là hình, mà đường truyền của
        # kho vốn đã chật. Muốn giữ tiếng thì khai audio: true, lúc đó chuyển
        # sang AAC cho MP4 nuốt được (nén tiếng 8kHz gần như không tốn CPU).
        if camera.get('audio'):
            args += ['-c:a', 'aac', '-b:a', '64k']
        else:
            args += ['-an']

    elif kind == 'usb':
        device = camera.get('device')
        if not device:
            raise ValueError(
                "camera usb thiếu 'device' (%s)"
                % ('tên thiết bị DirectShow' if IS_WINDOWS else 'đường dẫn /dev/videoN'))
        size = camera.get('size') or '1280x720'
        fps = str(camera.get('fps') or 24)
        bitrate = camera.get('bitrate') or '4M'
        # -rtbufsize: webcam đẩy frame chưa nén rất nặng, buffer nhỏ là rớt khung.
        # Chỉ Windows mới cần tiền tố "video=" và mới hiểu -rtbufsize kiểu này.
        args += ['-f', USB_INPUT_FORMAT]
        if IS_WINDOWS:
            args += ['-rtbufsize', '256M']
        args += ['-video_size', size, '-framerate', fps]
        args += ['-i', ('video=%s' % device) if IS_WINDOWS else device]
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
        self.camera_cfg = camera_cfg
        self.out_path = out_path          # file CUỐI CÙNG, sau khi nối các đoạn
        self.max_seconds = max_seconds
        self.ffmpeg_bin = ffmpeg_bin
        self.started_at = time.time()
        self.segments = []
        self.restarts = 0
        self.proc = None
        # Giữ chung cho cả bản ghi, không reset mỗi đoạn: lý do đứt ở đoạn trước
        # mới là thứ cần đọc khi cuối cùng phải báo hỏng.
        self._err_lines = collections.deque(maxlen=STDERR_KEEP_LINES)
        self._spawn()

    def elapsed(self):
        return time.time() - self.started_at

    def _next_segment_path(self):
        """Đường dẫn đoạn kế tiếp: <ten>_<id>.segNN.mp4.

        CỐ Ý không trùng dạng tên file cuối: hàm quét file tồn đọng tìm đuôi
        _<id>.mp4, nên đoạn dở dang không bị nhặt lên gửi nhầm.
        """
        base, ext = os.path.splitext(self.out_path)
        return '%s.seg%02d%s' % (base, len(self.segments), ext)

    def _spawn(self):
        """Chạy một tiến trình ffmpeg cho đoạn kế tiếp."""
        path = self._next_segment_path()
        # Trần thời gian tính theo phần CÒN LẠI của bản ghi, không phải trần đầy
        # đủ: chạy lại 20 lần mà lần nào cũng cho 30 phút thì một phiếu bỏ quên
        # có thể ghi hàng giờ.
        remaining = max(5, int(self.max_seconds - self.elapsed()))
        cmd = build_ffmpeg_args(self.camera_cfg, path, remaining, self.ffmpeg_bin)
        log.info("ffmpeg start rec=%s cam=%s -> %s", self.recording_id,
                 self.camera_code, path)
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, creationflags=NO_WINDOW,
        )
        self.segments.append(path)
        threading.Thread(target=self._drain_stderr, args=(self.proc,),
                         daemon=True).start()

    def try_restart(self):
        """ffmpeg chết giữa chừng mà chưa có lệnh dừng — ghi tiếp thành đoạn mới.

        Trả: True nếu đã chạy lại. False khi không nên chạy nữa (đã tới trần thời
            gian của bản ghi, hoặc đã chạy lại quá nhiều lần). Bên gọi khi đó
            chốt sổ bản ghi như bình thường.
        """
        if self.elapsed() >= self.max_seconds:
            return False
        if self.restarts >= MAX_SEGMENT_RESTARTS:
            log.warning("rec=%s đã chạy lại %d lần, thôi không chạy nữa",
                        self.recording_id, self.restarts)
            return False
        self.restarts += 1
        log.warning("rec=%s cam=%s luồng bị đứt, ghi tiếp đoạn %d",
                    self.recording_id, self.camera_code, len(self.segments))
        try:
            self._spawn()
        except OSError as exc:
            log.error("rec=%s không chạy lại được ffmpeg: %s", self.recording_id, exc)
            return False
        return True

    def finalize(self):
        """Nối các đoạn thành file cuối. Trả đường dẫn file cuối, hoặc None."""
        return concat_segments(self.segments, self.out_path, self.ffmpeg_bin)

        # PHẢI đọc stderr liên tục. ffmpeg kêu ra stderr suốt lúc chạy — camera
        # IP mất gói, DTS nhảy — và ống dẫn của tiến trình con chỉ có một bộ đệm
        # nhỏ (64KB trên Windows). Không ai đọc thì bộ đệm đầy, ffmpeg BỊ CHẶN
        # ngay tại lệnh ghi stderr và ngừng hẳn việc ghi hình, trong khi tiến
        # trình vẫn còn sống nên không chỗ nào báo hỏng. Kết quả: file đứng lại ở
        # vài MB. Đã đo: 42KB so với 7118KB trong cùng một khoảng thời gian.
        # Bàn hai camera dính nặng hơn vì luồng nào nhiễu hơn thì đầy trước.
        self._err_lines = collections.deque(maxlen=STDERR_KEEP_LINES)
        self._err_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._err_thread.start()

    def _drain_stderr(self, proc):
        """Đọc cạn stderr suốt đời MỘT tiến trình, giữ phần cuối để báo lỗi.

        Nhận tiến trình làm tham số chứ không đọc self.proc: sau khi chạy lại,
        self.proc đã trỏ sang tiến trình mới, luồng cũ phải đọc nốt ống cũ.
        """
        try:
            for line in iter(proc.stderr.readline, b''):
                self._err_lines.append(line.decode('utf-8', 'replace').rstrip())
        except (OSError, ValueError):
            pass  # ống đóng khi tiến trình chết — bình thường

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
        """Phần cuối những gì ffmpeg đã kêu. Rỗng nếu nó im lặng suốt."""
        # Luồng đọc là daemon và ống đã đóng khi tiến trình thoát, nên chỉ cần
        # nhường một nhịp cho nó gom nốt phần cuối.
        time.sleep(0.2)
        return '\n'.join(self._err_lines)[-limit:]


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
        self.last_update_try = 0.0
        self.exit_for_update = False

        # Gui file o LUONG RIENG. Truoc day upload chay thang trong vong lap
        # poll, nen suot ca chuc phut gui mot file lon, agent khong goi Odoo lan
        # nao — Odoo thay im lang lien ket luan "agent da ngung goi" va danh hong
        # moi phieu mo trong khoang do. Agent chua he chet, no tu bit mieng minh.
        self.upload_queue = queue.Queue()
        self.uploading = set()          # recording_id dang cho / dang gui
        self.upload_lock = threading.Lock()
        # Mot luong duy nhat: gui song song nhieu file chi lam nghen them duong
        # len von da hep cua kho.
        self.uploader = threading.Thread(target=self._upload_worker, daemon=True)

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
            # BAO CA nhung ban ghi co ffmpeg vua chet va dang cho chay lai.
            # Loc theo is_running() la sai: trong khe ho giua luc luong dut va luc
            # noi lai duoc, Odoo se thay ban ghi "khong con ai chay", danh hong no
            # roi gui lenh dung - giet dung luc agent dang cuu phieu do. Con nam
            # trong self.active nghia la agent VAN NHAN, chua buong.
            'active_ids': list(self.active),
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

    def _find_leftover_file(self, recording_id):
        """Tìm file quay còn nằm lại của một bản ghi. None nếu không có.

        Agent chết giữa chừng có thể để lại các đoạn .segNN chưa kịp nối — gom
        luôn, nếu không thì phiếu đó mất video dù bằng chứng vẫn nằm trên đĩa.
        """
        final_re = re.compile(r'_%d\.(?:mp4|mkv)$' % recording_id)
        seg_re = re.compile(r'_%d\.seg\d+\.(?:mp4|mkv)$' % recording_id)
        segments = []
        try:
            for name in sorted(os.listdir(self.work_dir)):
                path = os.path.join(self.work_dir, name)
                if final_re.search(name):
                    return path
                if seg_re.search(name):
                    segments.append(path)
        except OSError:
            return None
        if not segments:
            return None
        base = re.sub(r'\.seg\d+(\.(?:mp4|mkv))$', r'\1', segments[0])
        log.info("rec=%s còn %d đoạn chưa nối, ghép lại rồi gửi",
                 recording_id, len(segments))
        return concat_segments(segments, base, self.ffmpeg_bin)

    def stop_recording(self, recording_id):
        recorder = self.active.pop(recording_id, None)
        if not recorder:
            # Agent khởi động lại giữa chừng thì self.active mất sạch, nhưng Odoo
            # vẫn gửi lệnh dừng mỗi 2 giây. Trước đây hàm này return im lặng nên
            # bản ghi kẹt ở "Chờ agent dừng" VĨNH VIỄN và Odoo gửi lại lệnh mãi.
            # Phải trả lời: còn file thì gửi, không còn thì báo hỏng — bằng cách
            # nào cũng được, miễn là trạng thái được chốt.
            path = self._find_leftover_file(recording_id)
            if path:
                log.info("rec=%s: agent đã khởi động lại, gửi nốt file còn lại",
                         recording_id)
                self.enqueue_upload(recording_id, path)
            else:
                self.report_failure(
                    recording_id,
                    "agent khởi động lại giữa chừng: không còn tiến trình ghi "
                    "và không tìm thấy file quay nào cho bản ghi này")
            return
        recorder.stop()
        final = recorder.finalize()
        if recorder.restarts:
            log.info("rec=%s ghép từ %d đoạn (luồng đứt %d lần)", recording_id,
                     len(recorder.segments), recorder.restarts)
        if not final or not os.path.exists(final) or os.path.getsize(final) < 51200:
            stderr = recorder.stderr_tail()
            hint = explain_ffmpeg_error(stderr)
            self.report_failure(
                recording_id,
                ("ffmpeg không ghi được gì — %s\n\n%s" % (hint, stderr)) if hint
                else ("ffmpeg không ghi được gì: %s" % stderr))
            for path in recorder.segments:
                _remove(path)
            _remove(recorder.out_path)
            return
        # Xep vao hang doi chu KHONG gui ngay tai day: day dang la vong lap poll.
        self.enqueue_upload(recording_id, final)

    def enqueue_upload(self, recording_id, path):
        """Xep mot file vao hang doi gui. Bo qua neu no da nam trong hang doi."""
        with self.upload_lock:
            if recording_id in self.uploading:
                return False
            self.uploading.add(recording_id)
        self.upload_queue.put((recording_id, path))
        return True

    def _upload_worker(self):
        """Luong gui file, chay song song voi vong lap poll.

        Gui xong thi xoa file; gui hong thi GIU LAI de lan quet sau thu tiep.
        Nuot moi loi: luong nay chet la khong con ai gui file nua.
        """
        while True:
            item = self.upload_queue.get()
            if item is None:
                return
            recording_id, path = item
            try:
                if self.upload_to_drive(recording_id, path):
                    _remove(path)
                else:
                    log.error("giữ lại file chưa gửi được, sẽ tự thử lại sau %d giây: %s",
                              RETRY_SCAN_SECONDS, path)
            except Exception:
                log.exception("lỗi khi gửi rec=%s", recording_id)
            finally:
                with self.upload_lock:
                    self.uploading.discard(recording_id)
                self.upload_queue.task_done()

    def retry_pending_uploads(self):
        """Gui lai nhung file quay xong ma lan truoc gui khong duoc.

        Truoc day file chi duoc GIU LAI kem mot dong ERROR roi nam do vinh vien:
        video co that tren dia nhung khong bao gio toi Odoo — dung kieu mat bang
        chung im lang ma he thong nay sinh ra de tranh.

        Ma ban ghi nam trong ten file (..._<id>.mp4) nen doc lai duoc ca sau khi
        agent khoi dong lai. Bo qua file cua ban ghi DANG quay va file vua sinh
        ra, tranh dung vao file ffmpeg con dang ghi do.
        """
        try:
            names = sorted(os.listdir(self.work_dir))
        except OSError:
            return

        now = time.time()
        for name in names:
            if name.endswith(RESUME_SUFFIX):
                continue  # file ghi chu phien, khong phai video
            if not name.lower().endswith(('.mp4', '.mkv')):
                continue
            match = re.search(r'_(\d+)\.(?:mp4|mkv)$', name)
            if not match:
                continue
            recording_id = int(match.group(1))
            if recording_id in self.active:
                continue  # dang quay, chua toi luc gui

            path = os.path.join(self.work_dir, name)
            try:
                if now - os.path.getmtime(path) < RETRY_MIN_AGE_SECONDS:
                    continue
                size_mb = os.path.getsize(path) / 1024 / 1024
            except OSError:
                continue

            if self.enqueue_upload(recording_id, path):
                log.info("xếp lại vào hàng đợi gửi: rec=%s (%.1fMB)",
                         recording_id, size_mb)

    def sweep_finished(self):
        """ffmpeg chạm trần -t hoặc chết giữa chừng thì tự dọn, không chờ lệnh stop."""
        for recording_id in list(self.active):
            recorder = self.active[recording_id]
            if recorder.is_running():
                continue
            # ffmpeg dừng trước cả lệnh dừng: hoặc chạm trần -t (bình thường),
            # hoặc camera đứt giữa chừng (KHÔNG bình thường). Hai cái đó cho ra
            # video dài ngắn khác hẳn nhau. Trước đây chỉ ghi "tự kết thúc" rồi
            # gửi file đi, nên video vài giây không để lại dấu vết nào để truy.
            try:
                size_mb = os.path.getsize(recorder.out_path) / 1024 / 1024
            except OSError:
                size_mb = 0.0
            tail = recorder.stderr_tail()
            log.info("rec=%s cam=%s ffmpeg tự kết thúc (mã %s, %.1fMB)",
                     recording_id, recorder.camera_code,
                     recorder.proc.returncode, size_mb)
            if tail:
                log.warning("rec=%s ffmpeg kêu trước khi dừng: %s", recording_id, tail)

            # Phiếu CHƯA đóng mà luồng đã đứt: ghi tiếp, đừng chốt sổ. Một lần
            # chớp mạng chỉ được phép mất vài giây, không được mất cả phiếu.
            if recorder.try_restart():
                continue
            self.stop_recording(recording_id)

    # ---------------- tu cap nhat ----------------
    def is_idle(self):
        """Bàn này có đang rảnh không: không camera nào ghi, không file chờ gửi.

        Trả: True khi rảnh. Đây là điều kiện BẮT BUỘC trước khi tự cập nhật —
            khởi động lại giữa lúc đang quay là mất bằng chứng của phiếu đó, mà
            đó đúng là thứ cả hệ thống này sinh ra để chống.
        """
        if self.active:
            return False
        with self.upload_lock:
            return not self.uploading

    def _verify_agent_file(self, path):
        """Chạy thử file agent vừa tải. Trả (ok, mô tả).

        Đây là khâu chặn quan trọng nhất của việc tự cập nhật: mọi bàn cùng tải
        một file từ một nguồn, nên một file hỏng là chết đồng loạt. Gọi thẳng
        "python <file> --version" bắt được cả lỗi cú pháp lẫn lỗi thiếu thư
        viện, những thứ mà chỉ đọc dung lượng không thấy được.
        """
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            return False, 'không đọc được file vừa tải: %s' % exc
        if size < MIN_AGENT_BYTES:
            return False, 'file chỉ %d byte, quá nhỏ để là agent thật' % size

        try:
            proc = subprocess.run(
                [sys.executable, path, '--version'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=60, creationflags=NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, 'không chạy thử được: %s' % exc

        out = (proc.stdout or b'').decode('utf-8', 'replace').strip()
        if proc.returncode != 0:
            return False, 'chạy thử thất bại (mã %s): %s' % (proc.returncode, out[-300:])
        if not out:
            return False, 'chạy thử không in ra phiên bản nào'
        return True, out

    def self_update(self):
        """Tải bản agent mới từ Odoo, kiểm rồi thay file và thoát.

        Thoát là xong việc: Windows có cửa canh Scheduled Task, Linux có systemd
        Restart=always — cả hai đều bật lại agent, lúc đó nó chạy file mới.

        Không bao giờ ghi đè file đang chạy trước khi bản mới chạy thử được. Bản
        cũ được giữ lại ở đuôi .bak để còn quay về bằng tay.
        """
        now = time.time()
        if now - self.last_update_try < UPDATE_RETRY_SECONDS:
            return False
        self.last_update_try = now

        current = os.path.abspath(__file__)
        new_path = current + '.new'
        log.info("Odoo báo có bản agent mới, đang tải về")
        try:
            resp = self.session.get(
                '%s/pack_agent/download/agent' % self.base_url, timeout=120)
            resp.raise_for_status()
            with open(new_path, 'wb') as handle:
                handle.write(resp.content)
        except (requests.RequestException, OSError) as exc:
            log.error("không tải được bản agent mới: %s", exc)
            _remove(new_path)
            return False

        ok, detail = self._verify_agent_file(new_path)
        if not ok:
            # Giu nguyen ban dang chay. Mot ban hong khong duoc phep lam chet ban
            # dang chay ngon lanh - do la khac biet giua "khong cap nhat duoc" va
            # "ban dong goi ngung hoat dong".
            log.error("bản agent mới KHÔNG dùng được, giữ nguyên bản cũ: %s", detail)
            _remove(new_path)
            return False

        # Kiem lai lan cuoi ngay truoc khi thay: tai + chay thu mat vai giay, du
        # de mot phieu moi bat dau quay.
        if not self.is_idle():
            log.info("vừa có việc trong lúc tải, hoãn cập nhật tới lần rảnh sau")
            _remove(new_path)
            return False

        backup = current + '.bak'
        try:
            _remove(backup)
            shutil.copy2(current, backup)
            os.replace(new_path, current)
        except OSError as exc:
            log.error("không thay được file agent: %s", exc)
            _remove(new_path)
            return False

        log.info("đã cập nhật agent (%s), thoát để chạy bản mới", detail)
        # Thoat khac 0: tren Windows, Scheduled Task chi khoi dong lai sau 1 phut
        # khi tien trinh BAO LOI; thoat 0 thi phai doi cua canh 5 phut. systemd
        # Restart=always thi kieu nao cung bat lai sau 10 giay.
        self.running = False
        self.exit_for_update = True
        return True

    # ---------------- gửi file ----------------
    # ---------------- day thang len Google Drive ----------------
    def _resume_path(self, path):
        return path + RESUME_SUFFIX

    def _load_session(self, path):
        """Doc URL phien resumable da luu. None neu chua co."""
        try:
            with open(self._resume_path(path), encoding='utf-8') as fh:
                url = fh.read().strip()
            return url or None
        except OSError:
            return None

    def _save_session(self, path, session_url):
        try:
            with open(self._resume_path(path), 'w', encoding='utf-8') as fh:
                fh.write(session_url)
        except OSError:
            pass  # khong luu duoc thi chi mat kha nang noi lai, khong chet

    def _clear_session(self, path):
        _remove(self._resume_path(path))

    def _drive_start_session(self, ticket, size):
        """Mo mot phien resumable, tra ve URL phien (hoac None neu hong)."""
        meta = {'name': ticket['title'], 'parents': [ticket['folder_id']]}
        try:
            resp = self.session.post(
                DRIVE_UPLOAD_URL,
                headers={
                    'Authorization': 'Bearer %s' % ticket['access_token'],
                    'Content-Type': 'application/json; charset=UTF-8',
                    'X-Upload-Content-Type': ticket['mimetype'],
                    'X-Upload-Content-Length': str(size),
                },
                json=meta, timeout=60)
        except requests.RequestException as exc:
            log.warning("mở phiên Drive hỏng: %s", exc)
            return None
        if resp.status_code not in (200, 201):
            log.error("Drive từ chối mở phiên: HTTP %s %s",
                      resp.status_code, resp.text[:200])
            return None
        return resp.headers.get('Location')

    def _drive_offset(self, session_url, size):
        """Hoi Google da nhan toi byte nao roi.

        Tra ve so byte da nhan, hoac -1 neu phien khong con dung (phai mo lai),
        hoac dict ket qua neu file DA len xong tu lan truoc.
        """
        try:
            resp = self.session.put(
                session_url,
                headers={'Content-Range': 'bytes */%d' % size,
                         'Content-Length': '0'},
                timeout=60)
        except requests.RequestException as exc:
            log.warning("hỏi vị trí phiên Drive hỏng: %s", exc)
            return -1
        if resp.status_code in (200, 201):
            return resp.json()          # lan truoc da gui xong roi
        if resp.status_code != 308:
            return -1                    # phien het han / bi huy
        rng = resp.headers.get('Range')
        if not rng:
            return 0                     # chua nhan byte nao
        try:
            return int(rng.split('-')[-1]) + 1
        except (ValueError, IndexError):
            return 0

    def upload_to_drive(self, recording_id, path):
        """Day file len Drive, KHONG di qua Odoo.

        Odoo chi cap ve (token ngan han + thu muc + ten file) va nhan lai cai
        link. Moi byte video di thang toi Google — day la ly do 2 worker cua
        Odoo khong con bi chiem hang chuc phut moi lan gui video.

        Tra ve True neu xong. Dut giua chung thi GIU nguyen file va URL phien de
        lan sau gui tiep tu dung cho do.
        """
        size = os.path.getsize(path)
        ticket = self._call_json('/pack_agent/drive_ticket', {
            'recording_id': recording_id, 'ext': os.path.splitext(path)[1].lower(),
        }, timeout=120)

        if ticket is None:
            # Goi khong duoc: Odoo chua co route nay (agent moi hon Odoo), hoac
            # mang dut. Lui ve duong cu (gui qua Odoo) de khong phu thuoc thu tu
            # trien khai — cap nhat agent truoc khi build Odoo van chay duoc.
            log.warning("rec=%s không gọi được /pack_agent/drive_ticket, "
                        "lùi về đường gửi qua Odoo", recording_id)
            return self.upload(recording_id, path)

        if not ticket.get('ok'):
            # Odoo tra loi ro rang la tu choi (thieu token Drive, ban ghi la...).
            # Lui ve duong cu cung hong, nen bao that bai luon.
            log.error("rec=%s không lấy được vé Drive: %s",
                      recording_id, ticket.get('error'))
            return False

        session_url = self._load_session(path)
        offset = 0
        if session_url:
            got = self._drive_offset(session_url, size)
            if isinstance(got, dict):
                log.info("rec=%s lần trước đã lên xong Drive rồi", recording_id)
                return self._drive_report(recording_id, ticket, got, size, path)
            if got < 0:
                session_url = None       # phien hong, mo lai tu dau
            else:
                offset = got
                log.info("rec=%s nối tiếp từ %.1fMB/%.1fMB",
                         recording_id, offset / 1024 / 1024, size / 1024 / 1024)

        if not session_url:
            session_url = self._drive_start_session(ticket, size)
            if not session_url:
                return False
            self._save_session(path, session_url)
            offset = 0

        log.info("gửi rec=%s %.1fMB thẳng lên Drive", recording_id, size / 1024 / 1024)
        with open(path, 'rb') as fh:
            while offset < size:
                fh.seek(offset)
                chunk = fh.read(DRIVE_CHUNK_BYTES)
                end = offset + len(chunk) - 1
                try:
                    resp = self.session.put(
                        session_url,
                        headers={'Content-Range': 'bytes %d-%d/%d' % (offset, end, size)},
                        data=chunk, timeout=600)
                except requests.RequestException as exc:
                    log.warning("rec=%s đứt ở %.1fMB: %s — lần sau gửi tiếp từ đây",
                                recording_id, offset / 1024 / 1024, exc)
                    return False

                if resp.status_code == 308:
                    rng = resp.headers.get('Range')
                    offset = (int(rng.split('-')[-1]) + 1) if rng else end + 1
                    continue
                if resp.status_code in (200, 201):
                    return self._drive_report(recording_id, ticket, resp.json(),
                                              size, path)
                log.error("rec=%s Drive trả HTTP %s: %s", recording_id,
                          resp.status_code, resp.text[:200])
                return False
        return False

    def _drive_report(self, recording_id, ticket, drive_file, size, path):
        """Bao link ve Odoo. Bao duoc moi coi la xong."""
        link = drive_file.get('webViewLink') or (
            'https://drive.google.com/file/d/%s/view' % drive_file.get('id'))
        result = self._call_json('/pack_agent/drive_done', {
            'recording_id': recording_id,
            'link': link,
            'title': ticket['title'],
            'size_mb': round(size / 1024 / 1024, 1),
        }, timeout=60)
        if not result or not result.get('ok'):
            # File DA nam tren Drive roi. Khong bao duoc thi giu file lai de lan
            # sau bao — luc do _drive_offset se thay "da xong" va bao lai ngay,
            # khong gui lai byte nao.
            log.error("rec=%s đã lên Drive nhưng chưa báo được về Odoo: %s",
                      recording_id, result)
            return False
        self._clear_session(path)
        log.info("rec=%s gửi xong lên Drive", recording_id)
        return True

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
        self.uploader.start()
        ok_count = 0
        fail_count = 0
        last_pulse = time.time()
        # Quet ngay tu dau: agent vua khoi dong lai sau su co thi file ton dong
        # phai duoc gui di luon, khong cho them 2 phut.
        last_retry_scan = 0.0

        while self.running:
            try:
                self.sweep_finished()
                if time.time() - last_retry_scan >= RETRY_SCAN_SECONDS:
                    last_retry_scan = time.time()
                    self.retry_pending_uploads()

                result = self.poll()
                if result and result.get('ok'):
                    ok_count += 1
                    for command in result.get('commands') or []:
                        self.handle(command)
                    # Sau khi xu ly lenh: mot lenh start vua toi thi ban khong con
                    # ranh nua, va is_idle() se thay dieu do.
                    if result.get('update_agent') and self.is_idle():
                        self.self_update()
                elif result is not None:
                    fail_count += 1
                    log.error("Odoo từ chối: %s — kiểm lại station_key và token", result.get('error'))
                else:
                    fail_count += 1  # goi hong, poll() da ghi ly do
            except Exception:
                fail_count += 1
                log.exception("lỗi không lường trước trong vòng lặp")

            now = time.time()
            if now - last_pulse >= PULSE_SECONDS:
                with self.upload_lock:
                    pending = len(self.uploading)
                log.info("còn sống: %d lần gọi Odoo OK, %d lần hỏng, "
                         "%d camera đang ghi, %d file đang chờ gửi",
                         ok_count, fail_count, len(self.active), pending)
                ok_count = 0
                fail_count = 0
                last_pulse = now

            time.sleep(POLL_SECONDS)

        log.info("đang dừng, đóng nốt các file đang ghi")
        for recording_id in list(self.active):
            self.stop_recording(recording_id)
        # Cho gui not nhung gi dang trong hang doi, nhung co tran thoi gian: bi
        # tat may ma doi mai thi Windows/systemd se giet cung. File chua gui kip
        # van nam tren dia va se duoc gui o lan khoi dong sau.
        log.info("chờ gửi nốt %d file", self.upload_queue.qsize())
        deadline = time.time() + 60
        while not self.upload_queue.empty() and time.time() < deadline:
            time.sleep(1)

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


def _list_v4l2_devices():
    """In webcam Linux đang thấy, kèm mẫu YAML điền sẵn.

    Đọc thẳng /sys/class/video4linux thay vì parse output ffmpeg: tên thiết bị
    nằm sẵn ở đó, khỏi phụ thuộc định dạng log của ffmpeg đổi theo phiên bản.
    Biên: không có /dev/video* nào -> in hướng dẫn rồi trả 1.
    """
    import glob as _glob

    devices = sorted(_glob.glob('/dev/video*'))
    if not devices:
        print("Không thấy webcam nào (/dev/video*).")
        print("Camera IP thì không dùng lệnh này — khai thẳng URL RTSP vào agent.yaml.")
        return 1

    for dev in devices:
        name = ''
        sys_name = '/sys/class/video4linux/%s/name' % os.path.basename(dev)
        try:
            with open(sys_name, encoding='utf-8') as fh:
                name = fh.read().strip()
        except OSError:
            pass
        print()
        print('=' * 68)
        print('Webcam: %s%s' % (dev, (' — %s' % name) if name else ''))
        print()
        print('  Chép khối này vào mục cameras: trong agent.yaml,')
        print('  đổi "MA_CAMERA" thành đúng Mã camera khai trong Odoo:')
        print()
        print('    "MA_CAMERA":')
        print('      type: usb')
        print('      device: "%s"' % dev)
        print('      size: "1280x720"')
        print('      fps: 15')
        print('      bitrate: "3M"')
        print('      overlay_time: true')
    print()
    print("Xem chế độ thiết bị hỗ trợ:  v4l2-ctl --device %s --list-formats-ext" % devices[0])
    return 0


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


def concat_segments(segments, out_path, ffmpeg_bin):
    """Nối các đoạn quay thành một file, KHÔNG nén lại.

    segments: danh sách đường dẫn theo đúng thứ tự ghi.
    out_path: file đích.
    Trả: out_path nếu tạo được, None nếu không còn đoạn nào dùng được.
        Biên: chỉ còn một đoạn -> đổi tên, không gọi ffmpeg (nhanh và không
        có cơ hội hỏng). Đoạn rỗng/quá nhỏ bị bỏ trước khi nối.
    """
    usable = []
    for path in segments:
        try:
            if os.path.getsize(path) >= MIN_SEGMENT_BYTES:
                usable.append(path)
            else:
                _remove(path)
        except OSError:
            pass
    if not usable:
        return None
    if len(usable) == 1:
        try:
            os.replace(usable[0], out_path)
            return out_path
        except OSError as exc:
            log.error("không đổi tên được đoạn duy nhất: %s", exc)
            return usable[0]

    list_path = out_path + '.txt'
    try:
        with open(list_path, 'w', encoding='utf-8') as handle:
            for path in usable:
                # Bộ đọc danh sách của ffmpeg dùng nháy đơn; nháy đơn trong tên
                # phải thoát theo đúng kiểu của nó.
                safe = os.path.abspath(path).replace('\\', '/').replace("'", "'\\''")
                handle.write("file '%s'\n" % safe)
        cmd = [ffmpeg_bin, '-hide_banner', '-loglevel', 'warning',
               '-f', 'concat', '-safe', '0', '-i', list_path,
               '-c', 'copy', '-movflags', '+faststart', '-y', out_path]
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=600,
                              creationflags=NO_WINDOW)
        if proc.returncode != 0 or not os.path.exists(out_path):
            err = (proc.stderr or b'').decode('utf-8', 'replace')[-300:]
            log.error("nối đoạn thất bại (mã %s): %s", proc.returncode, err)
            # Tha ve doan DAI NHAT con hon tra ve khong co gi: van la bang chung.
            return max(usable, key=lambda p: os.path.getsize(p))
    except (OSError, subprocess.SubprocessError) as exc:
        log.error("nối đoạn lỗi: %s", exc)
        return max(usable, key=lambda p: os.path.getsize(p))
    finally:
        _remove(list_path)

    for path in usable:
        _remove(path)
    log.info("đã nối %d đoạn thành %s", len(usable), os.path.basename(out_path))
    return out_path


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
    # Dung cho khau kiem truoc khi tu cap nhat: chay duoc lenh nay nghia la file
    # khong loi cu phap va nap du thu vien.
    parser.add_argument('--version', action='store_true',
                        help="In phiên bản agent rồi thoát")
    args = parser.parse_args()

    if args.version:
        print(AGENT_VERSION)
        return 0

    _setup_logging(args)

    if not os.path.exists(args.config):
        log.error("không thấy file cấu hình: %s", args.config)
        return 2
    with open(args.config, encoding='utf-8') as fh:
        cfg = yaml.safe_load(fh) or {}

    if args.list_cameras:
        if IS_WINDOWS:
            return _list_dshow_devices(cfg.get('ffmpeg_path') or 'ffmpeg')
        return _list_v4l2_devices()

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
    # Thoat KHAC 0 sau khi tu cap nhat. Tren Windows, Scheduled Task chi khoi
    # dong lai sau 1 phut khi tien trinh bao loi; thoat 0 thi phai doi cua canh
    # 5 phut moi co agent tro lai - du lau de mot phieu bat dau ma khong ai ghi.
    return 3 if agent.exit_for_update else 0


if __name__ == '__main__':
    sys.exit(main())
