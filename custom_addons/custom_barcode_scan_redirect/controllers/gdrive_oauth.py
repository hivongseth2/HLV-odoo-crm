from odoo import http
from odoo.http import request
from werkzeug.utils import redirect
from werkzeug.wrappers import Response
import os, logging
from pydrive2.auth import GoogleAuth

_logger = logging.getLogger(__name__)
G_AUTH_URI   = "https://accounts.google.com/o/oauth2/auth"
G_TOKEN_URI  = "https://oauth2.googleapis.com/token"
G_REVOKE_URI = "https://oauth2.googleapis.com/revoke"
def _get_param(key, default=None):
    try:
        return request.env['ir.config_parameter'].sudo().get_param(key, default)
    except Exception:
        return default
def _build_settings_yaml(client_id, client_secret, redirect_uri, scopes_line):
    # chấp nhận ngăn cách bằng dấu cách hoặc dấu phẩy
    scopes = [s.strip() for s in (scopes_line or "").replace(",", " ").split() if s.strip()]
    if not scopes:
        scopes = ["https://www.googleapis.com/auth/drive.file"]
    scopes_block = "\n".join([f"  - {s}" for s in scopes])

    # YAML đầy đủ các khóa client_config (PyDrive2 yêu cầu)
    return (
        "client_config_backend: settings\n"
        "client_config:\n"
        f"  client_id: \"{client_id}\"\n"
        f"  client_secret: \"{client_secret}\"\n"
        f"  redirect_uri: \"{redirect_uri}\"\n"
        f"  auth_uri: \"{G_AUTH_URI}\"\n"
        f"  token_uri: \"{G_TOKEN_URI}\"\n"
        f"  revoke_uri: \"{G_REVOKE_URI}\"\n"
        "oauth_scope:\n"
        f"{scopes_block}\n"
        "get_refresh_token: True\n"
        "save_credentials: False\n"
    )

class GdriveOAuthController(http.Controller):


    @http.route('/gdrive/oauth2/start', type='http', auth='user', website=True, csrf=False)
    def start(self, **kw):
        cid   = _get_param('gdrive.oauth_client_id')
        csec  = _get_param('gdrive.oauth_client_secret')
        redir = _get_param('gdrive.oauth_redirect_uri')
        scopes = _get_param('gdrive.oauth_scopes', 'https://www.googleapis.com/auth/drive.file')
        if not (cid and csec and redir):
            return Response("Missing OAuth config (client_id/secret/redirect_uri).", status=500)

        # 1) Ghi settings.yaml
        tmpdir = os.path.join(os.path.expanduser('~'), '.gdrive_oauth')
        os.makedirs(tmpdir, exist_ok=True)
        settings_file = os.path.join(tmpdir, 'settings.yaml')
        with open(settings_file, 'w', encoding='utf-8') as f:
            f.write(_build_settings_yaml(cid, csec, redir, scopes))

        # 2) Ép cấu hình trong bộ nhớ (phòng YAML bị lỗi format)
        gauth = GoogleAuth(settings_file)
        scope_list = [s.strip() for s in (scopes or "").replace(",", " ").split() if s.strip()] \
                     or ["https://www.googleapis.com/auth/drive.file"]
        gauth.settings['client_config_backend'] = 'settings'
        gauth.settings['client_config'] = {
            'client_id': cid,
            'client_secret': csec,
            'redirect_uri': redir,
            'auth_uri': G_AUTH_URI,
            'token_uri': G_TOKEN_URI,
            'revoke_uri': G_REVOKE_URI,
        }
        gauth.settings['oauth_scope'] = scope_list
        gauth.settings['get_refresh_token'] = True
        gauth.settings['save_credentials'] = False

        # Tạo flow & redirect
        gauth.GetFlow()
        gauth.flow.params['access_type'] = 'offline'
        gauth.flow.params['prompt'] = 'consent'
        auth_url = gauth.GetAuthUrl()

        request.session['gdrive_settings_path'] = settings_file
        return redirect(auth_url)
    
    @http.route(
    ['/gdrive/oauth2/callback'],
    type='http', auth='user', website=True, csrf=False)  # <- website=True

    def callback(self, **kw):
        code = kw.get('code')
        if not code:
            return Response("Missing 'code' in callback", status=400)

        settings_file = request.session.get('gdrive_settings_path')
        if not settings_file or not os.path.exists(settings_file):
            return Response("OAuth session expired. Start again.", status=400)

        gauth = GoogleAuth(settings_file)
        try:
            gauth.Auth(code)
        except Exception as e:
            _logger.exception("OAuth exchange failed")
            return Response(f"OAuth exchange failed: {e}", status=500)

        creds_json = gauth.credentials.to_json()
        request.env['ir.config_parameter'].sudo().set_param('gdrive.user_credentials_json', creds_json)

        return Response(
            "<h3>✅ Đã kết nối Google Drive!</h3><p>Có thể đóng cửa sổ và thử upload lại.</p>",
            status=200, content_type='text/html; charset=utf-8'
        )
