
import os, subprocess, numpy as np, threading
from datetime import datetime
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

RTSP_URL = 'rtsp://admin:HoangLongVu@192.168.1.31:554/h264/ch1/main'
OUTPUT_DIR = '/opt/odoo/warehouse_videos'
MAX_DURATION = 120

# pygame.mixer.init(frequency=44100, size=-16, channels=2)

# def generate_beep():
#     sr = 44100
#     t = np.linspace(0, 0.5, int(sr * 0.5), endpoint=False)
#     wave = 0.5 * np.sin(2 * np.pi * 440 * t)
#     stereo_wave = (np.array([wave, wave]).T * 32767).astype(np.int16)
#     return pygame.sndarray.make_sound(np.ascontiguousarray(stereo_wave))

# beep_sound = generate_beep()

def play_notification():
    # beep_sound.play()
    print("🔔 Beep!")

def start_recording(barcode):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = os.path.join(OUTPUT_DIR, f"{barcode}.mp4")
    play_notification()

    cmd = [
        "ffmpeg", "-rtsp_transport", "tcp", "-i", RTSP_URL,
        "-t", str(MAX_DURATION),
        "-filter_complex",
        "[0:v]split=2[main][zoom];[zoom]crop=640:360:320:180,scale=320:180[zoomed];[main][zoomed]overlay=W-w-10:H-h-10[out]",
        "-map", "[out]",
        "-vcodec", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        output_file
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, output_file

def stop_process(proc):
    if proc and proc.poll() is None:
        try:
            proc.stdin.write(b"q\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except:
            proc.kill()

def init_drive():
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    return GoogleDrive(gauth)

drive = init_drive()

def get_or_create_folder(name, parent_id=None):
    query = f"title='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    folder_list = drive.ListFile({'q': query}).GetList()
    if folder_list:
        return folder_list[0]['id']
    metadata = {'title': name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        metadata['parents'] = [{'id': parent_id}]
    folder = drive.CreateFile(metadata)
    folder.Upload()
    return folder['id']

def upload_to_drive(filepath):
    file_name = os.path.basename(filepath)
    today_str = datetime.now().strftime("%d_%m_%Y")
    root_id = get_or_create_folder("KHO_HCM")
    day_id = get_or_create_folder(today_str, root_id)
    clip_id = get_or_create_folder("clip", day_id)

    gfile = drive.CreateFile({'title': file_name, 'parents': [{'id': clip_id}]})
    gfile.SetContentFile(filepath)
    gfile.Upload()

def upload_async(filepath):
    def worker():
        if os.path.exists(filepath):
            upload_to_drive(filepath)
    threading.Thread(target=worker, daemon=True).start()
