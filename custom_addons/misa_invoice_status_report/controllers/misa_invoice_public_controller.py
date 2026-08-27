import logging

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

# Trang này TRƯỚC ĐÂY dùng 1 mật khẩu chung (như /search_invoice, /sale_plan...) cho MỌI sale —
# nhược điểm: ai biết mật khẩu cũng thấy được TOÀN BỘ mã sale đã đăng ký
# (res.users.x_misa_saler_codes gộp chung của mọi user), không phân biệt được ai xem được mã
# nào. Đổi sang auth='user' (bắt buộc đăng nhập Odoo thật) để
# get_misa_invoice_saler_code_registry() chỉ trả về đúng mã của CHÍNH user đang đăng nhập
# (self.env.user) — 1 tài khoản có thể được gán nhiều mã sale, nhưng không thấy được mã của
# tài khoản khác. Chưa đăng nhập → Odoo tự chuyển hướng sang /web/login?redirect=/misa_sale_status
# (hành vi mặc định của auth='user'), không cần tự dựng form mật khẩu/session riêng nữa.


def _json_error(message):
    return {'status': 'error', 'message': message}


class MisaInvoicePublicController(http.Controller):

    @http.route('/misa_sale_status', type='http', auth='user', methods=['GET'], website=True)
    def misa_sale_status_page(self, **kwargs):
        return request.render('misa_invoice_status_report.misa_sale_status_page')

    @http.route('/misa_sale_status/api/saler_codes', type='json', auth='user', methods=['POST'])
    def api_saler_codes(self, **kwargs):
        codes = request.env['stock.picking'].sudo().get_misa_invoice_saler_code_registry()
        return {'status': 'success', 'codes': codes}

    @http.route('/misa_sale_status/api/list', type='json', auth='user', methods=['POST'])
    def api_list(
        self, saler_code='', search='', state='', date_from='', date_to='',
        multi_order_group=False, multi_request=False, limit=50, offset=0, **kwargs
    ):
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

    @http.route('/misa_sale_status/api/daily_stats', type='json', auth='user', methods=['POST'])
    def api_daily_stats(self, saler_code='', date_from='', date_to='', weekly=False, **kwargs):
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

    @http.route('/misa_sale_status/api/order_list', type='json', auth='user', methods=['POST'])
    def api_order_list(
        self, saler_code='', search='', state='', partial_coverage_only=False, mismatch_only=False,
        date_from='', date_to='', limit=20, offset=0, **kwargs
    ):
        try:
            data = request.env['stock.picking'].sudo().get_misa_invoice_public_order_list(
                saler_code=saler_code, search=search, state=state or False,
                partial_coverage_only=bool(partial_coverage_only), mismatch_only=bool(mismatch_only),
                date_from=date_from or False, date_to=date_to or False,
                limit=int(limit), offset=int(offset),
            )
            return {'status': 'success', 'data': data}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_order_list error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/shopee_list', type='json', auth='user', methods=['POST'])
    def api_shopee_list(self, saler_code='', search='', state='', date_from='', date_to='', limit=50, offset=0, **kwargs):
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

    @http.route('/misa_sale_status/api/reconciliation_totals', type='json', auth='user', methods=['POST'])
    def api_reconciliation_totals(self, saler_code='', date_from='', date_to='', **kwargs):
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

    @http.route('/misa_sale_status/api/picking_row', type='json', auth='user', methods=['POST'])
    def api_picking_row(self, picking_id=None, saler_code='', **kwargs):
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

    @http.route('/misa_sale_status/api/picking_siblings', type='json', auth='user', methods=['POST'])
    def api_picking_siblings(self, picking_id=None, saler_code='', **kwargs):
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

    @http.route('/misa_sale_status/api/customs/fetch', type='json', auth='user', methods=['POST'])
    def api_customs_fetch(self, inv_no='', **kwargs):
        try:
            preview = request.env['stock.picking'].sudo().fetch_misa_customs_invoice(inv_no)
            return {'status': 'success', 'preview': preview}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_fetch error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/customs/save', type='json', auth='user', methods=['POST'])
    def api_customs_save(self, inv_no='', **kwargs):
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

    @http.route('/misa_sale_status/api/customs/list', type='json', auth='user', methods=['POST'])
    def api_customs_list(self, saler_code='', search='', pending_only=False, limit=50, offset=0, **kwargs):
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

    @http.route('/misa_sale_status/api/customs/retry', type='json', auth='user', methods=['POST'])
    def api_customs_retry(self, line_id=None, **kwargs):
        try:
            result = request.env['stock.picking'].sudo().retry_misa_customs_match(int(line_id))
            return {'status': 'success', 'result': result}
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_retry error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/customs/retry_all', type='json', auth='user', methods=['POST'])
    def api_customs_retry_all(self, saler_code='', **kwargs):
        try:
            result = request.env['stock.picking'].sudo().retry_all_pending_customs_matches_public(saler_code)
            return {'status': 'success', 'result': result}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_retry_all error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/customs/search_pickings', type='json', auth='user', methods=['POST'])
    def api_customs_search_pickings(self, line_id=None, search='', **kwargs):
        try:
            rows = request.env['stock.picking'].sudo().search_pickings_for_customs_manual_match(
                int(line_id), search=search or False,
            )
            return {'status': 'success', 'rows': rows}
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_search_pickings error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/customs/manual_match', type='json', auth='user', methods=['POST'])
    def api_customs_manual_match(self, line_id=None, picking_id=None, quantity=False, **kwargs):
        try:
            result = request.env['stock.picking'].sudo().set_manual_customs_match(
                int(line_id), int(picking_id), quantity=quantity or False,
            )
            return {'status': 'success', 'result': result}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_manual_match error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/customs/remove_match', type='json', auth='user', methods=['POST'])
    def api_customs_remove_match(self, match_id=None, **kwargs):
        try:
            result = request.env['stock.picking'].sudo().remove_customs_match(int(match_id))
            return {'status': 'success', 'result': result}
        except Exception as e:
            _logger.exception('misa_sale_status api_customs_remove_match error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/check', type='json', auth='user', methods=['POST'])
    def api_check(self, picking_ids=None, saler_code='', **kwargs):
        try:
            ids = [int(x) for x in (picking_ids or [])]
            results = request.env['stock.picking'].sudo().action_public_check(ids, saler_code)
            return {'status': 'success', 'results': results}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_check error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/mark_exception', type='json', auth='user', methods=['POST'])
    def api_mark_exception(self, picking_ids=None, saler_code='', reason='', **kwargs):
        try:
            ids = [int(x) for x in (picking_ids or [])]
            result = request.env['stock.picking'].sudo().action_public_mark_exception(ids, saler_code, reason)
            return {'status': 'success', 'count': result.get('count', 0)}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_mark_exception error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/unmark_exception', type='json', auth='user', methods=['POST'])
    def api_unmark_exception(self, picking_ids=None, saler_code='', **kwargs):
        try:
            ids = [int(x) for x in (picking_ids or [])]
            result = request.env['stock.picking'].sudo().action_public_unmark_exception(ids, saler_code)
            return {'status': 'success', 'count': result.get('count', 0)}
        except UserError as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status api_unmark_exception error')
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/manual_link', type='json', auth='user', methods=['POST'])
    def api_manual_link(self, picking_id=None, saler_code='', refno='', **kwargs):
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
