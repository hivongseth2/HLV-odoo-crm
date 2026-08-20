"""Marks delivery planner snapshots dirty when stock move reservation/state changes affect sale orders.
"""

import logging
from odoo import models

_logger = logging.getLogger(__name__)

# Move state changes that affect dashboard stock/packing status
_MOVE_NOTIFY_FIELDS = {'state', 'quantity', 'picked'}


class StockMove(models.Model):
    _inherit = 'stock.move'

    def write(self, vals):
        res = super().write(vals)
        if vals and _MOVE_NOTIFY_FIELDS.intersection(vals.keys()):
            # Only notify for moves linked to sale orders (avoid noise from internal/MRP moves)
            if any(m.sale_line_id or (m.picking_id and m.picking_id.sale_id) for m in self[:5]):
                self._notify_delivery_planner_changed()
        if vals.get('state') == 'done':
            # Move này hoàn tất nghĩa là tồn kho THẬT SỰ thay đổi cho (các) sản phẩm của nó —
            # dù move này không thuộc đơn bán nào (VD phiếu nhập từ PO), các đơn KHÁC đang chờ
            # đúng sản phẩm đó cũng cần tính lại stock_status. Tách riêng khỏi check phía trên
            # vì phía trên chỉ bắt đơn của CHÍNH move này, không bắt được ảnh hưởng chéo.
            self._notify_delivery_planner_product_availability_changed()
        return res

    def _notify_delivery_planner_product_availability_changed(self):
        """Đánh dấu dirty cho MỌI đơn khác (chưa giao đủ) đang chờ đúng sản phẩm vừa có move
        hoàn tất — thay cho việc reset toàn bộ snapshot mỗi ngày (không kịp với ~24k dòng, xem
        delivery_planner_snapshot.cron_refresh_dirty_snapshots). Chỉ 1 query nhỏ, có index trên
        product_id/state, không quét toàn bộ đơn."""
        product_ids = self.mapped('product_id').ids
        if not product_ids:
            return
        self.env.cr.execute("""
            SELECT DISTINCT sol.order_id
              FROM sale_order_line sol
              JOIN sale_order so ON so.id = sol.order_id
             WHERE sol.product_id = ANY(%s)
               AND so.state IN ('sale', 'done')
               AND sol.product_uom_qty > COALESCE(sol.qty_delivered, 0)
        """, (product_ids,))
        so_ids = {row[0] for row in self.env.cr.fetchall()}
        if not so_ids:
            return
        try:
            self.env['hlv.delivery.planner.snapshot'].sudo().mark_dirty_for_sale_orders(
                so_ids, reason='stock.move.product_availability'
            )
        except Exception:
            _logger.debug('Failed to mark dirty for product availability change', exc_info=True)

    def _action_assign(self, *args, **kwargs):
        res = super()._action_assign(*args, **kwargs)
        # Reservation changed → stock status on dashboard may change
        if any(m.sale_line_id or (m.picking_id and m.picking_id.sale_id) for m in self[:5]):
            self._notify_delivery_planner_changed()
        return res

    def _do_unreserve(self):
        # Check before unreserve (recordset still has data)
        should_notify = any(m.sale_line_id or (m.picking_id and m.picking_id.sale_id) for m in self[:5])
        res = super()._do_unreserve()
        if should_notify:
            self._notify_delivery_planner_changed()
        return res

    def _notify_delivery_planner_changed(self):
        """Send bus notification with the affected SO ids so the dashboard can
        do a partial subset refresh instead of a full reload."""
        so_ids = set(self.mapped('sale_line_id.order_id').ids) | set(self.mapped('picking_id.sale_id').ids)
        if not so_ids:
            return
        try:
            from ..services.delivery_planner_stats import bump_stats_cache_version
            bump_stats_cache_version()
        except Exception:
            pass
        try:
            self.env['hlv.delivery.planner.snapshot'].sudo().mark_dirty_for_sale_orders(
                so_ids, reason='stock.move'
            )
        except Exception:
            pass
        try:
            self.env['bus.bus']._sendone(
                'delivery_planner_channel',
                'delivery_planner_data_changed',
                {'source': 'stock.move', 'sale_order_ids': list(so_ids)},
            )
        except Exception:
            _logger.debug('Failed to send delivery_planner_data_changed notification', exc_info=True)
