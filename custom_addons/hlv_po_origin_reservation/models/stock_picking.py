import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        # Ghi nhớ các phiếu nhập kho chưa hoàn thành trước khi validate
        incoming_pickings = self.filtered(
            lambda p: p.picking_type_code == 'incoming' and p.state != 'done'
        )

        res = super().button_validate()

        # Sau khi validate, chỉ xử lý những phiếu đã chuyển sang 'done'
        for picking in incoming_pickings:
            if picking.state == 'done':
                self._reserve_for_origin_sale_order(picking)

        return res

    def _reserve_for_origin_sale_order(self, picking):
        """Sau khi nhập kho, tìm SO từ PO.origin và giữ hàng cho đơn giao."""
        purchase_order = picking.purchase_id
        if not purchase_order or not purchase_order.origin:
            return

        origin = purchase_order.origin
        # Origin có thể chứa nhiều giá trị phân tách bởi dấu phẩy
        origin_parts = [p.strip() for p in origin.split(',') if p.strip()]

        SaleOrder = self.env['sale.order']

        for part in origin_parts:
            sale_order = SaleOrder.search([('name', '=', part)], limit=1)
            if not sale_order:
                continue

            if not sale_order.procurement_group_id:
                continue

            # Tìm phiếu giao hàng (outgoing) của SO cần giữ hàng
            delivery_pickings = self.env['stock.picking'].search([
                ('group_id', '=', sale_order.procurement_group_id.id),
                ('state', 'in', ['confirmed', 'waiting', 'partially_available']),
                ('picking_type_code', '=', 'outgoing'),
            ])

            if delivery_pickings:
                _logger.info(
                    'PO %s (origin=%s): Giữ hàng cho SO %s - phiếu giao: %s',
                    purchase_order.name,
                    origin,
                    sale_order.name,
                    ', '.join(delivery_pickings.mapped('name')),
                )
                delivery_pickings.action_assign()
