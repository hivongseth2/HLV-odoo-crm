import logging

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

# Dùng chung session/tham số mật khẩu với các trang public khác (/search_invoice, /sale_plan,
# /cancel-request...) — sale chỉ cần biết 1 mật khẩu chung để vào hết các trang tiện ích nội bộ.
SESSION_KEY_OK = "inv_pw_ok"
PW_PARAM_KEY = "website_public_inventory_18.search_password"


def _get_search_password():
    return request.env['ir.config_parameter'].sudo().get_param(PW_PARAM_KEY, default='') or ''


def _pw_allowed():
    conf = _get_search_password()
    return not conf or bool(request.session.get(SESSION_KEY_OK))


def _json_error(message):
    return {'status': 'error', 'message': message}


class MisaInvoicePublicController(http.Controller):

    @http.route('/misa_sale_status', type='http', auth='public', methods=['GET', 'POST'], website=True, csrf=True)
    def misa_sale_status_page(self, **kwargs):
        if not _pw_allowed():
            error = None
            if request.httprequest.method == 'POST':
                password = (kwargs.get('password') or '').strip()
                if password == _get_search_password():
                    request.session[SESSION_KEY_OK] = True
                    return request.redirect('/misa_sale_status')
                error = 'Mật khẩu không đúng. Vui lòng thử lại.'
            return request.render('misa_invoice_status_report.misa_sale_status_login', {'error': error})
        return request.render('misa_invoice_status_report.misa_sale_status_page')

    @http.route('/misa_sale_status/logout', type='http', auth='public', methods=['GET'])
    def misa_sale_status_logout(self, **kwargs):
        request.session.pop(SESSION_KEY_OK, None)
        return request.redirect('/misa_sale_status')

    @http.route('/misa_sale_status/api/saler_codes', type='json', auth='public', methods=['POST'])
    def api_saler_codes(self, **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        codes = request.env['stock.picking'].sudo().get_misa_invoice_saler_code_registry()
        return {'status': 'success', 'codes': codes}

    @http.route('/misa_sale_status/api/list', type='json', auth='public', methods=['POST'])
    def api_list(
        self, saler_code='', search='', state='', date_from='', date_to='',
        multi_order_group=False, multi_request=False, limit=50, offset=0, **kwargs
    ):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            data = request.env['stock.picking'].sudo().get_misa_invoice_public_list(
                saler_code=saler_code, search=search, state=state or False,
                date_from=date_from or False, date_to=date_to or False,
                multi_order_group=bool(multi_order_group), multi_request=bool(multi_request),
                limit=int(limit), offset=int(offset),
            )
            return {'status': 'success', 'data': data}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_list error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/daily_stats', type='json', auth='public', methods=['POST'])
    def api_daily_stats(self, saler_code='', date_from='', date_to='', weekly=False, **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            buckets = request.env['stock.picking'].sudo().get_misa_invoice_public_daily_stats(
                saler_code=saler_code, date_from=date_from or False, date_to=date_to or False,
                weekly=bool(weekly),
            )
            return {'status': 'success', 'buckets': buckets}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_daily_stats error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/shopee_list', type='json', auth='public', methods=['POST'])
    def api_shopee_list(self, saler_code='', search='', state='', date_from='', date_to='', limit=50, offset=0, **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            data = request.env['stock.picking'].sudo().get_misa_invoice_public_shopee_list(
                saler_code=saler_code, search=search, state=state or False,
                date_from=date_from or False, date_to=date_to or False,
                limit=int(limit), offset=int(offset),
            )
            return {'status': 'success', 'data': data}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_shopee_list error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/reconciliation_totals', type='json', auth='public', methods=['POST'])
    def api_reconciliation_totals(self, saler_code='', date_from='', date_to='', **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            data = request.env['stock.picking'].sudo().get_misa_invoice_public_reconciliation_totals(
                saler_code=saler_code, date_from=date_from or False, date_to=date_to or False,
            )
            return {'status': 'success', 'data': data}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_reconciliation_totals error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/picking_row', type='json', auth='public', methods=['POST'])
    def api_picking_row(self, picking_id=None, saler_code='', **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            row = request.env['stock.picking'].sudo().get_misa_invoice_public_picking_row(
                int(picking_id), saler_code
            )
            return {'status': 'success', 'row': row}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_picking_row error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/picking_siblings', type='json', auth='public', methods=['POST'])
    def api_picking_siblings(self, picking_id=None, saler_code='', **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            siblings = request.env['stock.picking'].sudo().get_misa_invoice_public_picking_siblings(
                int(picking_id), saler_code
            )
            return {'status': 'success', 'siblings': siblings}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_picking_siblings error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/customs/fetch', type='json', auth='public', methods=['POST'])
    def api_customs_fetch(self, inv_no='', **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            preview = request.env['stock.picking'].sudo().fetch_misa_customs_invoice(inv_no)
            return {'status': 'success', 'preview': preview}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_fetch error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/customs/save', type='json', auth='public', methods=['POST'])
    def api_customs_save(self, inv_no='', **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            result = request.env['stock.picking'].sudo().save_misa_customs_invoice(inv_no)
            return {
                'status': 'success', 'count': result.get('count', 0),
                'matched_count': result.get('matched_count', 0), 'invoice_no': result.get('invoice_no'),
            }
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_save error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/customs/list', type='json', auth='public', methods=['POST'])
    def api_customs_list(self, saler_code='', search='', pending_only=False, limit=50, offset=0, **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            data = request.env['stock.picking'].sudo().get_misa_invoice_public_customs_lines(
                saler_code=saler_code, search=search or False, pending_only=bool(pending_only),
                limit=int(limit), offset=int(offset),
            )
            return {'status': 'success', 'data': data}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_list error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/customs/retry', type='json', auth='public', methods=['POST'])
    def api_customs_retry(self, line_id=None, **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            result = request.env['stock.picking'].sudo().retry_misa_customs_match(int(line_id))
            return {'status': 'success', 'result': result}
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_retry error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/customs/delete', type='json', auth='public', methods=['POST'])
    def api_customs_delete(self, inv_no='', **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            count = request.env['stock.picking'].sudo().delete_misa_customs_invoice(inv_no)
            return {'status': 'success', 'count': count}
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_delete error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/check', type='json', auth='public', methods=['POST'])
    def api_check(self, picking_ids=None, saler_code='', **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            ids = [int(x) for x in (picking_ids or [])]
            results = request.env['stock.picking'].sudo().action_public_check(ids, saler_code)
            return {'status': 'success', 'results': results}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_check error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/mark_exception', type='json', auth='public', methods=['POST'])
    def api_mark_exception(self, picking_ids=None, saler_code='', reason='', **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            ids = [int(x) for x in (picking_ids or [])]
            result = request.env['stock.picking'].sudo().action_public_mark_exception(ids, saler_code, reason)
            return {'status': 'success', 'count': result.get('count', 0)}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_mark_exception error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/unmark_exception', type='json', auth='public', methods=['POST'])
    def api_unmark_exception(self, picking_ids=None, saler_code='', **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            ids = [int(x) for x in (picking_ids or [])]
            result = request.env['stock.picking'].sudo().action_public_unmark_exception(ids, saler_code)
            return {'status': 'success', 'count': result.get('count', 0)}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_unmark_exception error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/manual_link', type='json', auth='public', methods=['POST'])
    def api_manual_link(self, picking_id=None, saler_code='', refno='', **kwargs):
        if not _pw_allowed():
            return _json_error('unauthorized')
        try:
            result = request.env['stock.picking'].sudo().action_public_manual_link(
                int(picking_id), saler_code, refno
            )
            if result.get('error'):
                return _json_error('Lỗi kiểm tra MISA: %s' % result['error'])
            warning = None
            if result.get('state') != 'invoiced':
                warning = 'Đã lưu mã đề nghị. MISA hiện báo trạng thái: %s' % (
                    result.get('state_label') or result.get('state')
                )
            return {
                'status': 'success', 'warning': warning,
                'state': result.get('state'), 'state_label': result.get('state_label'),
            }
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_manual_link error')
            return _json_error(str(e))
