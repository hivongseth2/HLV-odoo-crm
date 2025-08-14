import os, json, base64, logging
from datetime import datetime
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from odoo.http import request  # để đọc system parameters khi có request context

_logger = logging.getLogger(__name__)

# thư mục an toàn để ghi file tạm trên Odoo.sh
SA_DIR = os.path.join(os.path.expanduser('~'), '.gdrive')
SA_FILE = os.path.join(SA_DIR, 'service_account.json')
SETTINGS_FILE = os.path.join(SA_DIR, 'settings.yaml')

def _get_param(key, default=None):
    """Đọc ENV trước, thiếu thì đọc System Parameters."""
    val = os.environ.get(key)
    if val is not None:
        return val
    try:
        return request.env['ir.config_parameter'].sudo().get_param(key, default)
    except Exception:
        return default

def _materialize_service_account_file() -> str:
    """Tạo file service_account.json từ ENV hoặc System Params."""
    os.makedirs(SA_DIR, exist_ok=True)
    if os.path.exists(SA_FILE):
        return SA_FILE

    b64 = _get_param('GDRIVE_SERVICE_ACCOUNT_JSON_B64') \
          or _get_param('gdrive.service_account_json_b64')
    raw = _get_param('GDRIVE_SERVICE_ACCOUNT_JSON') \
          or _get_param('gdrive.service_account_json')

    if not b64 and not raw:
        raise RuntimeError(
            "Thiếu service account JSON. Hãy set "
            "gdrive.service_account_json_b64 (hoặc gdrive.service_account_json)."
        )

    try:
        data = base64.b64decode(b64) if b64 else raw.encode('utf-8')
        # xác nhận JSON hợp lệ
        json.loads(data.decode('utf-8'))
        with open(SA_FILE, 'wb') as f:
            f.write(data)
        return SA_FILE
    except Exception as e:
        raise RuntimeError(f"Không tạo được service_account.json từ secret: {e}")

def _write_settings_file(sa_path: str):
    content = f"""
client_config_backend: service
service_config:
  client_json_file_path: {sa_path}
oauth_scope:
  - https://www.googleapis.com/auth/drive
  - https://www.googleapis.com/auth/drive.file
""".strip()
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        f.write(content)

class DriveManager:
    def __init__(self):
        self.drive = None
        self.root_folder = None
        self.anyone_link = False
        self.root_folder_id = None
        self._init_drive()

    def _init_drive(self):
        sa_path = _materialize_service_account_file()
        _write_settings_file(sa_path)

        self.root_folder = _get_param('GDRIVE_ROOT_FOLDER', _get_param('gdrive.root_folder', 'KHO_HCM'))
        self.anyone_link = str(_get_param('GDRIVE_ANYONE_LINK', _get_param('gdrive.anyone_link', 'false'))).lower() == 'true'

        gauth = GoogleAuth(SETTINGS_FILE)
        gauth.ServiceAuth()   # KHÔNG cần mở trình duyệt
        self.drive = GoogleDrive(gauth)

        self.root_folder_id = self.get_or_create_folder(self.root_folder)
        _logger.info("✅ Google Drive SA ready. Root: %s", self.root_folder)

    def get_or_create_folder(self, name, parent_id=None):
        q = "mimeType='application/vnd.google-apps.folder' and trashed=false and title='%s'" % name.replace("'", "\\'")
        if parent_id:
            q += f" and '{parent_id}' in parents"
        items = self.drive.ListFile({'q': q}).GetList()
        if items:
            return items[0]['id']
        meta = {'title': name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_id:
            meta['parents'] = [{'id': parent_id}]
        f = self.drive.CreateFile(meta)
        f.Upload()
        return f['id']

    def _ensure_path(self):
        # root / dd_mm_yyyy / clip
        day = datetime.now().strftime("%d_%m_%Y")
        day_id = self.get_or_create_folder(day, self.root_folder_id)
        clip_id = self.get_or_create_folder("clip", day_id)
        return clip_id

    def upload_file(self, local_path, title=None, mimetype='video/webm'):
        try:
            parent_id = self._ensure_path()
            if not title:
                base = os.path.splitext(os.path.basename(local_path))[0]
                title = f"{base}.webm" if mimetype == 'video/webm' else os.path.basename(local_path)

            gfile = self.drive.CreateFile({'title': title, 'parents': [{'id': parent_id}]})
            if mimetype:
                gfile['mimeType'] = mimetype
            gfile.SetContentFile(local_path)
            gfile.Upload()

            file_id = gfile['id']
            web_link = gfile.get('alternateLink') or f"https://drive.google.com/file/d/{file_id}/view"

            if self.anyone_link:
                try:
                    gfile.InsertPermission({'type': 'anyone', 'value': 'me', 'role': 'reader'})
                except Exception as e:
                    _logger.warning("Set public link failed: %s", e)

            try:
                gfile.content.close()
            except Exception:
                pass

            _logger.info("✅ Uploaded to Drive: %s (%s)", title, file_id)
            return True, file_id, web_link
        except Exception as e:
            _logger.error("❌ Drive upload failed: %s", e, exc_info=True)
            return False, None, None

# Singleton
_manager = None
def get_drive_manager():
    global _manager
    if _manager is None:
        _manager = DriveManager()
    return _manager
