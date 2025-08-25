# -*- coding: utf-8 -*-
import os, logging
from datetime import datetime

from odoo import api, SUPERUSER_ID
from odoo import registry as odoo_registry

# KHÔNG dựa vào request trong background
try:
    from odoo.http import request
except Exception:
    request = None

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.client import OAuth2Credentials

_logger = logging.getLogger(__name__)

OAUTH_DIR = os.path.join(os.path.expanduser('~'), '.gdrive_oauth')
SETTINGS_FILE = os.path.join(OAUTH_DIR, 'settings_runtime.yaml')

# Endpoint v2
G_AUTH_URI   = "https://accounts.google.com/o/oauth2/v2/auth"
G_TOKEN_URI  = "https://oauth2.googleapis.com/token"
G_REVOKE_URI = "https://oauth2.googleapis.com/revoke"


class DriveManager:
    """Safe cho cả request thread và background thread."""
    def __init__(self, dbname: str):
        if not dbname:
            raise ValueError("DriveManager requires dbname")
        self.dbname = dbname
        self.drive = None
        self.root_folder_name = None
        self.root_folder_id = None
        self.anyone_link = False
        self._init_drive()

    # ==== Helpers lấy cấu hình, KHÔNG dùng request.env khi chạy thread ====
    def _get_param(self, key, default=None):
        # ưu tiên request.env nếu có (trong request thread)
        if request is not None and getattr(request, "env", None):
            try:
                return request.env['ir.config_parameter'].sudo().get_param(key, default)
            except Exception:
                pass
        # fallback: mở registry từ dbname (background-safe)
        with odoo_registry(self.dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            return env['ir.config_parameter'].sudo().get_param(key, default)

    def _write_settings(self):
        cid   = self._get_param('gdrive.oauth_client_id')
        csec  = self._get_param('gdrive.oauth_client_secret')
        redir = self._get_param('gdrive.oauth_redirect_uri')
        scopes_line = self._get_param('gdrive.oauth_scopes', 'https://www.googleapis.com/auth/drive.file')
        scopes = [s.strip() for s in (scopes_line or '').replace(',', ' ').split() if s.strip()] \
                 or ['https://www.googleapis.com/auth/drive.file']

        os.makedirs(OAUTH_DIR, exist_ok=True)
        scopes_block = '\n'.join([f'  - {s}' for s in scopes])
        content = (
            "client_config_backend: settings\n"
            "client_config:\n"
            f"  client_id: \"{cid}\"\n"
            f"  client_secret: \"{csec}\"\n"
            f"  redirect_uri: \"{redir}\"\n"
            f"  auth_uri: \"{G_AUTH_URI}\"\n"
            f"  token_uri: \"{G_TOKEN_URI}\"\n"
            f"  revoke_uri: \"{G_REVOKE_URI}\"\n"
            "oauth_scope:\n"
            f"{scopes_block}\n"
            "get_refresh_token: True\n"
            "save_credentials: False\n"
        )
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            f.write(content)

    def _init_drive(self):
        creds_json = self._get_param('gdrive.user_credentials_json')
        if not creds_json:
            raise RuntimeError("Chưa kết nối Google Drive. Truy cập /gdrive/oauth2/start để cấp quyền.")

        self._write_settings()  # đảm bảo settings có đủ trường
        gauth = GoogleAuth(SETTINGS_FILE)
        gauth.credentials = OAuth2Credentials.from_json(creds_json)

        try:
            if gauth.access_token_expired:
                gauth.Refresh()
        except Exception as e:
            _logger.warning("Refresh token failed: %s", e)
            # Xoá token để người dùng kết nối lại
            with odoo_registry(self.dbname).cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env['ir.config_parameter'].sudo().set_param('gdrive.user_credentials_json', '')
            raise RuntimeError("Token hết hạn hoặc bị thu hồi. Vào /gdrive/oauth2/start để kết nối lại.")

        self.drive = GoogleDrive(gauth)
        self.root_folder_name = self._get_param('gdrive.root_folder', 'KHO_HCM')
        self.anyone_link = str(self._get_param('gdrive.anyone_link', 'false')).lower() == 'true'
        self.root_folder_id = self.get_or_create_folder(self.root_folder_name)

        _logger.info("✅ Google Drive OAuth ready. Root=%s (id=%s)", self.root_folder_name, self.root_folder_id)

    # ==== Drive utils ====
    def _list(self, q):
        return self.drive.ListFile({'q': q}).GetList()

    def get_or_create_folder(self, name, parent_id=None):
        q = "mimeType='application/vnd.google-apps.folder' and trashed=false and title='%s'" % name.replace("'", "\\'")
        if parent_id:
            q += f" and '{parent_id}' in parents"
        found = self._list(q)
        if found:
            return found[0]['id']
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
                title = os.path.basename(local_path)

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


# ==== Factory (per-db) ====
_managers = {}  # cache theo dbname
def get_drive_manager(dbname: str):
    mgr = _managers.get(dbname)
    if mgr is None:
        mgr = DriveManager(dbname)
        _managers[dbname] = mgr
    return mgr
