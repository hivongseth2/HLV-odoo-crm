from odoo import http
from odoo.http import request
from werkzeug.utils import redirect
from werkzeug.wrappers import Response
import os, logging
from pydrive2.auth import GoogleAuth

_logger = logging.getLogger(__name__)

def _get_param(key, default=None):
    try:
        return request.env['ir.config_parameter'].sudo().get_param(key, default)
    except Exception:
        return default

def _build_settings_yaml(client_id, client_secret, redirect_uri, scopes_line):
    scopes = [s.strip() for s in scopes_line.split()] if scopes_line else ["https://www.googleapis.com/auth/drive.file"]
    scopes_block = "".join([f"  - {s}\n" for s in scopes])
    return f"""client_config_backend: settings
    client_config:
    client_id: {client_id}
    client_secret: {client_secret}
    redirect_uri: {redirect_uri}
    oauth_scope:
    {scopes_block}get_refresh_token: True
    save_credentials: False
    """

class GdriveOAuthController(http.Controller):

    @http.route(
        ['/gdrive/oauth2/start'],
        type='http', auth='user', website=True, csrf=False)  # <- website=True
    def start(self, **kw):
        cid   = _get_param('gdrive.oauth_client_id')
        csec  = _get_param('gdrive.oauth_client_secret')
        redir = _get_param('gdrive.oauth_redirect_uri')
        scopes = _get_param('gdrive.oauth_scopes', 'https://www.googleapis.com/auth/drive.file')
        if not (cid and csec and redir):
            return Response("Missing OAuth config (client_id/secret/redirect_uri).", status=500)

        tmpdir = os.path.join(os.path.expanduser('~'), '.gdrive_oauth')
        os.makedirs(tmpdir, exist_ok=True)
        settings_file = os.path.join(tmpdir, 'settings.yaml')
        with open(settings_file, 'w', encoding='utf-8') as f:
            f.write(_build_settings_yaml(cid, csec, redir, scopes))

        gauth = GoogleAuth(settings_file)
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
