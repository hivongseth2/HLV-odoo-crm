import os
import ffmpeg
import threading
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

RTSP_URL = 'rtsp://admin:HoangLongVu@192.168.1.31:554/h264/ch1/main'
OUTPUT_DIR = '/tmp/warehouse_videos'
MAX_DURATION = 120  # in seconds

SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), 'credentials', 'service_account.json')

def play_notification():
    print("🔔 Beep!")

def start_recording(barcode):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = os.path.join(OUTPUT_DIR, f"{barcode}.mp4")
    play_notification()

    # Dùng ffmpeg-python
    try:
        (
            ffmpeg
            .input(RTSP_URL, rtsp_transport='tcp', t=MAX_DURATION)
            .filter_multi_output('split')[0]
            .filter('crop', 640, 360, 320, 180)
            .filter('scale', 320, 180)
            .overlay(ffmpeg.input(RTSP_URL, rtsp_transport='tcp', t=MAX_DURATION))
            .output(output_file, vcodec='libx264', preset='ultrafast', pix_fmt='yuv420p', movflags='+faststart')
            .run(overwrite_output=True)
        )
    except ffmpeg.Error as e:
        print('FFmpeg error:', e.stderr.decode())
    return output_file

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_or_create_folder(service, name="KHO_HCM", parent_id=None):
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = service.files().list(q=query, spaces='drive',
                                   fields="files(id, name)").execute()
    items = results.get('files', [])
    if items:
        return items[0]['id']
    file_metadata = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    if parent_id:
        file_metadata['parents'] = [parent_id]
    folder = service.files().create(body=file_metadata,
                                    fields='id').execute()
    return folder['id']

def upload_to_drive(filepath):
    service = get_drive_service()
    file_name = os.path.basename(filepath)
    today_str = datetime.now().strftime("%d_%m_%Y")

    root_id = get_or_create_folder(service, "KHO_HCM")
    day_id = get_or_create_folder(service, today_str, root_id)
    clip_id = get_or_create_folder(service, "clip", day_id)

    file_metadata = {
        'name': file_name,
        'parents': [clip_id]
    }
    media = MediaFileUpload(filepath, mimetype='video/mp4')
    service.files().create(body=file_metadata, media_body=media).execute()

def upload_async(filepath):
    def worker():
        if os.path.exists(filepath):
            upload_to_drive(filepath)
    threading.Thread(target=worker, daemon=True).start()
