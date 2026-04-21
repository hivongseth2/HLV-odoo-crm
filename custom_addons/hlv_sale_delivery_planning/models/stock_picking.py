import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

# Fields whose changes should trigger a real-time dashboard refresh
_PICK_NOTIFY_FIELDS = {
    'state', 'x_printed', 'carrier_id', 'carrier_tracking_ref',
    'scheduled_date', 'date_done', 'x_bien_ban_printed',
}


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_printed = fields.Boolean(
        string='Đã in phiếu lấy hàng',
        default=False,
        copy=False,
        help='Đánh dấu tự động khi phiếu được in từ màn hình điều phối giao hàng',
    )

    x_bien_ban_printed = fields.Boolean(
        string='Đã in biên bản',
        default=False,
        copy=False,
        help='Đánh dấu tự động khi in các report như: biên bản giao nhận/bàn giao, BBGN, BBBG, PXBH, phiếu xuất, phiếu bàn giao... cho phiếu này.',
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
        """Send bus notification with the affected SO ids so the dashboard can
        do a partial subset refresh instead of a full reload."""
        so_ids = list(set(self.mapped('sale_id').ids))
        if not so_ids:
            return
        try:
            from ..services.delivery_planner_stats import bump_stats_cache_version
            bump_stats_cache_version()
        except Exception:
            pass
        try:
            self.env['bus.bus']._sendone(
                'delivery_planner_channel',
                'delivery_planner_data_changed',
                {'source': 'stock.picking', 'sale_order_ids': so_ids},
            )
        except Exception:
            _logger.debug('Failed to send delivery_planner_data_changed notification', exc_info=True)
