import os, json, logging
from datetime import datetime
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.client import OAuth2Credentials
from odoo.http import request

_logger = logging.getLogger(__name__)

OAUTH_DIR = os.path.join(os.path.expanduser('~'), '.gdrive_oauth')
SETTINGS_FILE = os.path.join(OAUTH_DIR, 'settings_runtime.yaml')

def _get_param(key, default=None):
    try:
        return request.env['ir.config_parameter'].sudo().get_param(key, default)
    except Exception:
        return default

def _write_settings(scopes_line: str):
    os.makedirs(OAUTH_DIR, exist_ok=True)
    scopes = [s.strip() for s in (scopes_line or "").split()] or ["https://www.googleapis.com/auth/drive.file"]
    scopes_block = "".join([f"  - {s}\n" for s in scopes])
    content = f"""client_config_backend: settings
oauth_scope:
{scopes_block}save_credentials: False
"""
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        f.write(content)

class DriveManager:
    def __init__(self):
        self.drive = None
        self.root_folder_name = None
        self.root_folder_id = None
        self.anyone_link = False
        self._init_drive()

    def _init_drive(self):
        creds_json = _get_param('gdrive.user_credentials_json')
        if not creds_json:
            raise RuntimeError("Chưa kết nối Google Drive. Vào /gdrive/oauth2/start để cấp quyền.")

        scopes = _get_param('gdrive.oauth_scopes', 'https://www.googleapis.com/auth/drive.file')
        _write_settings(scopes)

        gauth = GoogleAuth(SETTINGS_FILE)
        gauth.credentials = OAuth2Credentials.from_json(creds_json)
        try:
            if gauth.access_token_expired:
                gauth.Refresh()
        except Exception as e:
            # refresh token có thể hết hạn/ bị revoke → xoá để user kết nối lại
            _logger.warning("Refresh token failed: %s", e)
            request.env['ir.config_parameter'].sudo().set_param('gdrive.user_credentials_json', '')
            raise RuntimeError("Token hết hạn hoặc bị thu hồi. Vào /gdrive/oauth2/start để kết nối lại.")

        self.drive = GoogleDrive(gauth)
        self.root_folder_name = _get_param('gdrive.root_folder', 'KHO_HCM')
        self.anyone_link = str(_get_param('gdrive.anyone_link', 'false')).lower() == 'true'
        self.root_folder_id = self.get_or_create_folder(self.root_folder_name, parent_id=None)
        _logger.info("✅ Google Drive OAuth ready. Root: %s (id=%s)", self.root_folder_name, self.root_folder_id)

    def _listfile(self, query):
        # My Drive, không dùng supportsAllDrives
        return self.drive.ListFile({'q': query}).GetList()

    def get_or_create_folder(self, name, parent_id=None):
        q = "mimeType='application/vnd.google-apps.folder' and trashed=false and title='%s'" % name.replace("'", "\\'")
        if parent_id:
            q += f" and '{parent_id}' in parents"
        items = self._listfile(q)
        if items:
            return items[0]['id']
        meta = {'title': name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_id:
            meta['parents'] = [{'id': parent_id}]
        f = self.drive.CreateFile(meta)
        f.Upload()
        return f['id']

    def _ensure_path(self):
        day = datetime.now().strftime("%d_%m_%Y")
        day_id = self.get_or_create_folder(day, parent_id=self.root_folder_id)
        clip_id = self.get_or_create_folder("clip", parent_id=day_id)
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

            _logger.info("✅ Uploaded to My Drive: %s (%s)", title, file_id)
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
