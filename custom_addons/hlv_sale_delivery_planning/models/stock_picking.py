import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

# Fields whose changes should trigger a real-time dashboard refresh
_PICK_NOTIFY_FIELDS = {
    'state', 'x_printed', 'carrier_id', 'carrier_tracking_ref',
    'scheduled_date', 'date_done', 'x_bien_ban_printed',
    'shipper_received', 'shipper_returned', 'shipper_user_id', 'shipper_received_by',
    'x_packer_id', 'x_packing_status', 'x_packing_print_time',
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

    x_packer_id = fields.Many2one(
        'res.users',
        string='Người đóng hàng',
        copy=False,
        help='Nhân viên phụ trách đóng gói đơn hàng này',
    )

    x_packing_print_time = fields.Datetime(
        string='Thời gian in phiếu',
        copy=False,
        help='Thời điểm bắt đầu in phiếu đóng hàng',
    )

    x_packing_finish_time = fields.Datetime(
        string='Thời gian hoàn thành đóng hàng',
        copy=False,
        help='Thời điểm xác nhận hoàn thành đóng hàng',
    )

    x_packing_status = fields.Selection(
        [('pending', 'Đang chờ'), ('packing', 'Đang đóng'), ('packed', 'Đã hoàn thành')],
        string='Trạng thái đóng hàng',
        default='pending',
        copy=False,
        help='Trạng thái đóng gói để theo dõi tiến độ và biết ai đang rảnh/bận',
    )

    def write(self, vals):
        res = super().write(vals)
        if vals and _PICK_NOTIFY_FIELDS.intersection(vals.keys()):
            self._notify_delivery_planner_changed()
        return res

    def _action_done(self):
        res = super()._action_done()
        # Auto-complete packing status khi validate phiếu PACK đang đóng
        pack_pickings = self.filtered(
            lambda p: p.x_packing_status == 'packing'
            and 'PACK' in (p.picking_type_id.sequence_code or '').upper()
        )
        if pack_pickings:
            pack_pickings.write({
                'x_packing_status': 'packed',
                'x_packing_finish_time': fields.Datetime.now(),
            })
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
