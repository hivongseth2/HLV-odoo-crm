"""RPC cho ô tick "Đã hoàn tất thủ tục sẵn sàng giao".

Dùng chung cho cả trang /sale_plan (public JS gọi qua controller) và trang
Điều phối Giao hàng (OWL gọi thẳng model). Chỉ đơn của khách có trong
hlv.delivery.procedure.partner mới được phép tick — FE ẩn ô tick, đây là chốt
chặn phía server.
"""

import logging

import pytz
from markupsafe import Markup

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class DeliveryPlannerServiceProcedure(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    @api.model
    def _format_procedure_datetime(self, value):
        if not value:
            return ''
        try:
            user_tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'Asia/Ho_Chi_Minh')
        except Exception:
            user_tz = pytz.UTC
        return value.replace(tzinfo=pytz.UTC).astimezone(user_tz).strftime('%d/%m/%Y %H:%M')

    @api.model
    def get_order_procedure_state(self, order):
        """Payload ô tick thủ tục cho 1 đơn (dùng trong formatter dashboard)."""
        requires = self.env['hlv.delivery.procedure.partner'].order_requires_procedure(order)
        return {
            'requires_procedure': requires,
            'procedure_done': bool(order.x_plan_procedure_done),
            'procedure_done_by': order.x_plan_procedure_done_by.name or '',
            'procedure_done_at': self._format_procedure_datetime(order.x_plan_procedure_done_at),
        }

    @api.model
    def set_order_procedure_done(self, order_id, done=True):
        """Tick / bỏ tick "đã hoàn tất thủ tục" cho một đơn."""
        so = self.env['sale.order'].sudo().browse(int(order_id or 0))
        if not so.exists():
            return {'success': False, 'message': 'Không tìm thấy đơn hàng.'}
        if not self.env['hlv.delivery.procedure.partner'].order_requires_procedure(so):
            return {
                'success': False,
                'message': 'Khách hàng của đơn này không thuộc danh sách cần xác nhận thủ tục.',
            }

        done = bool(done)
        if bool(so.x_plan_procedure_done) == done:
            # Hai người bấm gần như cùng lúc — không ghi đè người xác nhận trước.
            return {'success': True, **self.get_order_procedure_state(so)}

        so.write({
            'x_plan_procedure_done': done,
            'x_plan_procedure_done_by': self.env.uid if done else False,
            'x_plan_procedure_done_at': fields.Datetime.now() if done else False,
        })

        user_name = self.env.user.name or ''
        body = Markup('<p>%s <strong>%s</strong> — %s</p>') % (
            '✅' if done else '↩️',
            'Đã hoàn tất thủ tục sẵn sàng giao' if done else 'Bỏ xác nhận hoàn tất thủ tục',
            user_name,
        )
        try:
            so.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')
        except Exception:
            _logger.exception('set_order_procedure_done: message_post lỗi cho SO %s', so.id)

        return {'success': True, **self.get_order_procedure_state(so)}
