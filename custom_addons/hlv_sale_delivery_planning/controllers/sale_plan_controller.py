# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

SESSION_KEY_OK = "inv_pw_ok"
PW_PARAM_KEY   = "website_public_inventory_18.search_password"
VIEWER_PW_KEY  = "hlv_sale_delivery_planning.viewer_password"
VIEWER_LOGIN   = "sale_plan_viewer"
_H = [("Content-Type", "text/html; charset=utf-8")]

# ─── Login form ───────────────────────────────────────────────────────────────
_LOGIN = u"""<!DOCTYPE html>
<html lang="vi"><head>
<meta charset="utf-8"/>
<title>T\u00ecnh tr\u1ea1ng \u0110\u01a1n h\u00e0ng</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="min-height:100vh">
<div class="card shadow p-4" style="max-width:400px;width:100%">
  <h4 class="fw-bold text-center text-primary mb-3">&#128666; T\u00ecnh tr\u1ea1ng \u0110\u01a1n h\u00e0ng</h4>
  {err}
  <form method="post" action="/sale_plan">
    <input type="hidden" name="csrf_token" value="{csrf}"/>
    <label class="form-label fw-bold">M\u1eadt kh\u1ea9u</label>
    <input type="password" name="inv_password" class="form-control form-control-lg mb-3" autofocus required/>
    <button type="submit" class="btn btn-primary w-100 btn-lg">X\u00e1c nh\u1eadn</button>
  </form>
</div>
</body></html>"""

_ERR_PW = (
    u'<div class="alert alert-danger mb-3">'
    u'M\u1eadt kh\u1ea9u kh\u00f4ng \u0111\u00fang.</div>'
)

_ERR_VIEWER = u"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"/>
<title>C\u1ea5u h\u00ecnh thi\u1ebfu</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="min-height:100vh">
<div class="card shadow p-4 text-center" style="max-width:520px;width:100%">
  <h4 class="text-danger fw-bold mb-3">&#9888; Ch\u01b0a c\u1ea5u h\u00ecnh Viewer Account</h4>
  <p class="text-muted mb-3">Admin c\u1ea7n th\u1ef1c hi\u1ec7n 2 b\u01b0\u1edbc:</p>
  <ol class="text-start">
    <li class="mb-2">T\u1ea1o Odoo user v\u1edbi login: <code>sale_plan_viewer</code><br/>
        (Internal User, ch\u1ec9 c\u1ea7n quy\u1ec1n \u0111\u1ecdc Sales &amp; Inventory)</li>
    <li>V\u00e0o <b>Settings \u2192 Technical \u2192 Parameters \u2192 System Parameters</b>,<br/>
        t\u1ea1o key: <code>hlv_sale_delivery_planning.viewer_password</code><br/>
        value: password c\u1ee7a user tr\u00ean</li>
  </ol>
  <a href="/sale_plan" class="btn btn-secondary mt-2">&#8592; Quay l\u1ea1i</a>
</div>
</body></html>"""

_ERR_AUTH = u"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"/>
<title>L\u1ed7i \u0111\u0103ng nh\u1eadp Viewer</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="min-height:100vh">
<div class="card shadow p-4" style="max-width:560px;width:100%">
  <h4 class="text-danger fw-bold mb-3">&#9888; \u0110\u0103ng nh\u1eadp viewer th\u1ea5t b\u1ea1i</h4>
  <p class="text-muted mb-2">User <code>sale_plan_viewer</code> kh\u00f4ng \u0111\u0103ng nh\u1eadp \u0111\u01b0\u1ee3c. Ki\u1ec3m tra:</p>
  <ul class="text-start mb-3">
    <li>User ch\u01b0a b\u1ecb \u1eadn/kh\u00f3a (Settings \u2192 Users)</li>
    <li>Password trong System Parameters kh\u1edbp v\u1edbi password c\u1ee7a user</li>
    <li>Key parameter \u0111\u00fang: <code>hlv_sale_delivery_planning.viewer_password</code></li>
  </ul>
  <div class="alert alert-secondary small"><b>Chi ti\u1ebft l\u1ed7i:</b> {detail}</div>
  <a href="/sale_plan" class="btn btn-secondary mt-2">&#8592; Quay l\u1ea1i</a>
</div>
</body></html>"""

# ─── Wrapper: fullscreen iframe + hide Odoo navbar via CSS injection ──────────
_VIEWER_FRAME = u"""<!DOCTYPE html>
<html style="margin:0;padding:0;height:100%;overflow:hidden">
<head>
<meta charset="utf-8"/>
<title>T\u00ecnh tr\u1ea1ng \u0110\u01a1n h\u00e0ng</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  *,html,body{{margin:0;padding:0;box-sizing:border-box}}
  #hlv-frame{{position:fixed;top:0;left:0;width:100%;height:100%;border:none}}
</style>
</head>
<body>
<iframe id="hlv-frame"
  src="/web#action=hlv_sale_delivery_planning.action_delivery_planner_dashboard">
</iframe>
<script>
(function(){{
  // CSS injected into the iframe to hide Odoo top navbar
  var CSS = [
    'nav.o_main_navbar {{ display: none !important; }}',
    '.o_web_client {{ padding-top: 0 !important; }}',
    '.o_action_manager {{ top: 0 !important; height: 100vh !important; }}',
  ].join('\\n');

  var frame = document.getElementById('hlv-frame');
  var timer;

  function inject() {{
    try {{
      var doc = frame.contentDocument || frame.contentWindow.document;
      if (!doc || !doc.head) return;
      if (doc.getElementById('_hlv_no_nav')) return;
      var s = doc.createElement('style');
      s.id = '_hlv_no_nav';
      s.textContent = CSS;
      doc.head.appendChild(s);
    }} catch(e) {{}}
  }}

  // Re-inject every 400ms to survive SPA route changes
  frame.addEventListener('load', function() {{
    clearInterval(timer);
    inject();
    timer = setInterval(inject, 400);
  }});
}})();
</script>
</body>
</html>"""


class SalePlanPublicController(http.Controller):

    def _auto_login_viewer(self):
        """Authenticate the current session as the dedicated read-only viewer user.
        Returns (True, '') on success, or (False, error_message) on failure.
        """
        viewer_pw = (
            request.env['ir.config_parameter'].sudo()
            .get_param(VIEWER_PW_KEY, default='') or ''
        )
        if not viewer_pw:
            _logger.warning(
                'sale_plan_viewer: system parameter "%s" is empty or missing', VIEWER_PW_KEY
            )
            return False, 'not_configured'
        try:
            uid = request.session.authenticate(VIEWER_LOGIN, viewer_pw)
            if uid:
                return True, ''
            return False, 'bad_credentials'
        except Exception as e:
            _logger.exception('sale_plan_viewer: authenticate() failed: %s', e)
            return False, str(e)

    @http.route('/sale_plan', type='http', auth='public', methods=['GET', 'POST'])
    def sale_plan_page(self, **kwargs):
        # ── Already have an Odoo session (viewer or normal user) → show dashboard
        if request.session.uid:
            return request.make_response(_VIEWER_FRAME, headers=_H)

        # ── Check public password ────────────────────────────────────────────
        conf_pw = (
            request.env['ir.config_parameter'].sudo()
            .get_param(PW_PARAM_KEY, default='') or ''
        )

        if request.httprequest.method == 'POST':
            inp = (request.params.get('inv_password') or '').strip()
            if inp == conf_pw:
                ok, err_detail = self._auto_login_viewer()
                if not ok:
                    if err_detail == 'not_configured':
                        return request.make_response(_ERR_VIEWER, headers=_H)
                    # Auth failed — show debug info so admin can fix
                    return request.make_response(
                        _ERR_AUTH.format(detail=err_detail or 'unknown'),
                        headers=_H,
                    )
                # Viewer authenticated — redirect so GET serves the frame
                return request.redirect('/sale_plan')
            return request.make_response(
                _LOGIN.format(csrf=request.csrf_token(), err=_ERR_PW),
                headers=_H,
            )

        return request.make_response(
            _LOGIN.format(csrf=request.csrf_token(), err=''),
            headers=_H,
        )
