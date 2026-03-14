# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

SESSION_KEY_OK = "inv_pw_ok"
PW_PARAM_KEY   = "website_public_inventory_18.search_password"
VIEWER_PW_KEY  = "hlv_sale_delivery_planning.viewer_password"
VIEWER_LOGIN   = "sale_plan_viewer"
BACKEND_URL    = "/web#action=hlv_sale_delivery_planning.action_delivery_planner_dashboard"
_H = [("Content-Type", "text/html; charset=utf-8")]

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
<div class="card shadow p-4 text-center" style="max-width:500px;width:100%">
  <h4 class="text-danger fw-bold mb-3">&#9888; Ch\u01b0a c\u1ea5u h\u00ecnh Viewer Account</h4>
  <p class="text-muted">Admin c\u1ea7n th\u1ef1c hi\u1ec7n 2 b\u01b0\u1edbc:</p>
  <ol class="text-start">
    <li class="mb-2">T\u1ea1o Odoo user v\u1edbi login: <code>sale_plan_viewer</code> (Internal User, read-only)</li>
    <li>V\u00e0o <b>Settings &rarr; Technical &rarr; Parameters &rarr; System Parameters</b>,<br/>
        t\u1ea1o key: <code>hlv_sale_delivery_planning.viewer_password</code><br/>
        value: password c\u1ee7a user tr\u00ean</li>
  </ol>
  <a href="/sale_plan" class="btn btn-secondary mt-2">&#8592; Quay l\u1ea1i</a>
</div>
</body></html>"""


class SalePlanPublicController(http.Controller):

    def _auto_login_viewer(self):
        """Authenticate current session as the dedicated viewer user.
        Returns True on success, False if config is missing or auth fails.
        """
        viewer_pw = (
            request.env["ir.config_parameter"].sudo()
            .get_param(VIEWER_PW_KEY, default="") or ""
        )
        if not viewer_pw:
            return False
        try:
            uid = request.session.authenticate(request.db, VIEWER_LOGIN, viewer_pw)
            return bool(uid)
        except Exception:
            return False

    @http.route('/sale_plan', type='http', auth='public', methods=['GET', 'POST'])
    def sale_plan_page(self, **kwargs):
        # ── 1. Check public password ─────────────────────────────────────────
        if not request.session.get(SESSION_KEY_OK):
            conf_pw = (
                request.env["ir.config_parameter"].sudo()
                .get_param(PW_PARAM_KEY, default="") or ""
            )
            if request.httprequest.method == 'POST':
                inp = (request.params.get('inv_password') or '').strip()
                if inp == conf_pw:
                    request.session[SESSION_KEY_OK] = True
                    # fall through to step 2
                else:
                    return request.make_response(
                        _LOGIN.format(csrf=request.csrf_token(), err=_ERR_PW),
                        headers=_H,
                    )
            else:
                return request.make_response(
                    _LOGIN.format(csrf=request.csrf_token(), err=''),
                    headers=_H,
                )

        # ── 2. Log in as viewer if not already in an Odoo session ────────────
        if not request.session.uid:
            ok = self._auto_login_viewer()
            if not ok:
                # Viewer account not configured — show setup guide
                request.session.pop(SESSION_KEY_OK, None)
                return request.make_response(_ERR_VIEWER, headers=_H)

        # ── 3. Redirect to the real OWL dashboard ────────────────────────────
        return request.redirect(BACKEND_URL)
