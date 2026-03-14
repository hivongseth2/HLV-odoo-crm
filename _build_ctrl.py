# -*- coding: utf-8 -*-
"""Write sale_plan_controller.py – public read-only delivery dashboard."""
import textwrap, os

TARGET = (
    r"d:\HLV\HLV-odoo-crm\custom_addons\hlv_sale_delivery_planning"
    r"\controllers\sale_plan_controller.py"
)

# ── We split the page into a separate .html served from static ──────────────
# Controller provides: login form, main page serving, public JSON API.

CONTROLLER = textwrap.dedent(r'''
# -*- coding: utf-8 -*-
import logging
import time
from collections import defaultdict
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# ─── Rate limiting ────────────────────────────────────────────────────────────
_FAIL_LOG = defaultdict(list)
_RL_MAX = 5
_RL_WINDOW = 600

def _is_rate_limited(ip):
    now = time.time()
    recent = [t for t in _FAIL_LOG[ip] if now - t < _RL_WINDOW]
    _FAIL_LOG[ip] = recent
    return len(recent) >= _RL_MAX

def _record_failure(ip):
    _FAIL_LOG[ip].append(time.time())
    _logger.warning('sale_plan: login failed from %s (%d recent)', ip, len(_FAIL_LOG[ip]))

# ─── Constants ────────────────────────────────────────────────────────────────
SESSION_KEY_OK = "inv_pw_ok"
PW_PARAM_KEY = "website_public_inventory_18.search_password"
_H = [("Content-Type", "text/html; charset=utf-8")]

_ERR_PW = '<div class="alert alert-danger mb-3">M\u1eadt kh\u1ea9u kh\u00f4ng \u0111\u00fang.</div>'
_ERR_RATE = (
    '<div class="alert alert-danger mb-3">'
    'Qu\u00e1 nhi\u1ec1u l\u1ea7n th\u1eed sai. Vui l\u00f2ng '
    '<strong>th\u1eed l\u1ea1i sau 10 ph\u00fat</strong>.</div>'
)

_LOGIN = """<!DOCTYPE html>
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


class SalePlanPublicController(http.Controller):

    @http.route('/sale_plan', type='http', auth='public', methods=['GET', 'POST'])
    def sale_plan_page(self, **kwargs):
        ip = request.httprequest.remote_addr
        conf_pw = (
            request.env['ir.config_parameter'].sudo()
            .get_param(PW_PARAM_KEY, default='') or ''
        )

        # If password is configured and not yet authenticated
        if conf_pw and not request.session.get(SESSION_KEY_OK):
            if request.httprequest.method == 'POST':
                if _is_rate_limited(ip):
                    return request.make_response(
                        _LOGIN.format(csrf=request.csrf_token(), err=_ERR_RATE),
                        headers=_H,
                    )
                inp = (request.params.get('inv_password') or '').strip()
                if inp == conf_pw:
                    request.session[SESSION_KEY_OK] = True
                    _FAIL_LOG.pop(ip, None)
                    return request.redirect('/sale_plan')
                _record_failure(ip)
                return request.make_response(
                    _LOGIN.format(csrf=request.csrf_token(), err=_ERR_PW),
                    headers=_H,
                )
            return request.make_response(
                _LOGIN.format(csrf=request.csrf_token(), err=''),
                headers=_H,
            )

        # Serve the static dashboard page
        return request.redirect(
            '/hlv_sale_delivery_planning/static/src/public/sale_plan.html'
        )

    @http.route('/api/sale_plan/data', type='json', auth='public', methods=['POST'])
    def api_sale_plan_data(
        self, search='', warehouse_id='all', delivery_status='all',
        stock_status='all', packing_status='all',
        date_from='', date_to='',
        po_date_from='', po_date_to='', po_status='all',
        limit=12, offset=0, **kwargs
    ):
        conf_pw = (
            request.env['ir.config_parameter'].sudo()
            .get_param(PW_PARAM_KEY, default='') or ''
        )
        if conf_pw and not request.session.get(SESSION_KEY_OK):
            return {'status': 'error', 'message': 'Unauthorized'}

        result = (
            request.env['hlv.delivery.planner.service'].sudo()
            .get_dashboard_data(
                search_query=search,
                filter_warehouse_id=warehouse_id,
                filter_delivery_status=delivery_status,
                filter_stock_status=stock_status,
                filter_packing_status=packing_status,
                filter_date_from=date_from or '',
                filter_date_to=date_to or '',
                filter_po_date_from=po_date_from or '',
                filter_po_date_to=po_date_to or '',
                filter_po_status=po_status,
                limit=int(limit),
                offset=int(offset),
            )
        )
        return {'status': 'success', 'data': result}
''').lstrip()

with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(CONTROLLER)
print('Controller written OK')
