import logging

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


def _json_error(message):
    return {'status': 'error', 'message': message}


class MisaReceivableController(http.Controller):
    """Tab "Công nợ phải thu" của trang /misa_sale_status — cùng kiểu auth='user' + sudo như các
    API khác của trang; quyền theo mã sale nằm trong model (xem misa_receivable_public_api)."""

    def _call(self, name, method, *args, **kwargs):
        try:
            return {'status': 'success', 'data': getattr(request.env['misa.sale.payment.line'].sudo(), method)(*args, **kwargs)}
        except (UserError, AccessError, ValueError) as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status %s error', name)
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/receivable/list', type='json', auth='user', methods=['POST'])
    def api_receivable_list(
        self, saler_code='', search='', paid_filter='unpaid', month='', bucket='', limit=50, offset=0, **kwargs
    ):
        return self._call(
            'api_receivable_list', 'get_public_receivable_list', saler_code,
            search=search or False, paid_filter=paid_filter or 'unpaid', month=month or False,
            bucket=bucket or False, limit=int(limit), offset=int(offset),
        )

    @http.route('/misa_sale_status/api/receivable/lines', type='json', auth='user', methods=['POST'])
    def api_receivable_lines(self, saler_code='', invoice_key='', **kwargs):
        return self._call('api_receivable_lines', 'get_public_receivable_lines', saler_code, invoice_key)

    @http.route('/misa_sale_status/api/receivable/followup', type='json', auth='user', methods=['POST'])
    def api_receivable_followup(self, saler_code='', invoice_key='', promise_date='', collect_rate=None, note='', **kwargs):
        return self._call(
            'api_receivable_followup', 'update_public_receivable_followup', saler_code, invoice_key,
            promise_date=promise_date or False, collect_rate=collect_rate, note=note,
        )

    @http.route('/misa_sale_status/api/receivable/recheck', type='json', auth='user', methods=['POST'])
    def api_receivable_recheck(self, saler_code='', invoice_key='', **kwargs):
        return self._call('api_receivable_recheck', 'recheck_public_invoice', saler_code, invoice_key)

    @http.route('/misa_sale_status/api/receivable/sync', type='json', auth='user', methods=['POST'])
    def api_receivable_sync(self, **kwargs):
        return self._call('api_receivable_sync', 'request_public_receivable_sync')
