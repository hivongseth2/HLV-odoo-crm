import logging

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


def _json_error(message):
    return {'status': 'error', 'message': message}


class LoyaltySaleConfirmController(http.Controller):
    """Tab "Điểm đổi thưởng" của trang /misa_sale_status — cùng kiểu auth='user' + sudo như các
    API khác của trang; quyền theo mã sale nằm trong model (xem loyalty_history_sale_confirm)."""

    def _call(self, name, method, *args, **kwargs):
        try:
            return {'status': 'success', 'data': getattr(request.env['hlv.loyalty.history'].sudo(), method)(*args, **kwargs)}
        except (UserError, AccessError, ValueError) as e:
            return _json_error(str(e))
        except Exception as e:
            _logger.exception('misa_sale_status %s error', name)
            return _json_error(str(e))

    @http.route('/misa_sale_status/api/loyalty/list', type='json', auth='user', methods=['POST'])
    def api_loyalty_list(self, saler_code='', search='', limit=50, offset=0, **kwargs):
        return self._call(
            'api_loyalty_list', 'get_sale_public_pending_points', saler_code,
            search=search or False, limit=int(limit), offset=int(offset),
        )

    @http.route('/misa_sale_status/api/loyalty/check_paid', type='json', auth='user', methods=['POST'])
    def api_loyalty_check_paid(self, saler_code='', history_id=0, **kwargs):
        return self._call('api_loyalty_check_paid', 'action_sale_public_check_paid', saler_code, history_id)

    @http.route('/misa_sale_status/api/loyalty/confirm', type='json', auth='user', methods=['POST'])
    def api_loyalty_confirm(self, saler_code='', history_ids=None, **kwargs):
        return self._call('api_loyalty_confirm', 'action_sale_public_confirm', saler_code, history_ids)

    @http.route('/misa_sale_status/api/loyalty/cancel', type='json', auth='user', methods=['POST'])
    def api_loyalty_cancel(self, saler_code='', history_ids=None, reason='', **kwargs):
        return self._call('api_loyalty_cancel', 'action_sale_public_cancel', saler_code, history_ids, reason)

    @http.route('/misa_sale_status/api/loyalty/edit', type='json', auth='user', methods=['POST'])
    def api_loyalty_edit(self, saler_code='', history_id=0, point_amount=None, reason='', **kwargs):
        return self._call('api_loyalty_edit', 'action_sale_public_edit', saler_code, history_id, point_amount, reason)

    @http.route('/misa_sale_status/api/loyalty/recalculate', type='json', auth='user', methods=['POST'])
    def api_loyalty_recalculate(self, saler_code='', history_id=0, **kwargs):
        return self._call('api_loyalty_recalculate', 'action_sale_public_recalculate', saler_code, history_id)
