import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

# Fields whose changes should trigger a real-time dashboard refresh
_PICK_NOTIFY_FIELDS = {
    'state', 'x_printed', 'carrier_id', 'carrier_tracking_ref',
    'scheduled_date', 'date_done',
}


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_printed = fields.Boolean(
        string='Đã in phiếu lấy hàng',
        default=False,
        copy=False,
        help='Đánh dấu tự động khi phiếu được in từ màn hình điều phối giao hàng',
    )

    def write(self, vals):
        res = super().write(vals)
        if vals and _PICK_NOTIFY_FIELDS.intersection(vals.keys()):
            self._notify_delivery_planner_changed()
        return res

    def _action_done(self):
        res = super()._action_done()
        self._notify_delivery_planner_changed()
        return res

    def _notify_delivery_planner_changed(self):
        """Send bus notification so the delivery planner dashboard refreshes instantly.
        Uses context flag to send at most ONE notification per request cycle."""
        if self.env.context.get('_dp_notified'):
            return
        try:
            self.env['bus.bus']._sendone(
                'delivery_planner_channel',
                'delivery_planner_data_changed',
                {'source': 'stock.picking'},
            )
            self.env.context = dict(self.env.context, _dp_notified=True)
        except Exception:
            _logger.debug('Failed to send delivery_planner_data_changed notification', exc_info=True)
