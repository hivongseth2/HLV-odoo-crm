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
        """Sau khi nhập kho, tìm SO từ PO.origin rồi ưu tiên giữ hàng cho phiếu Pick."""
        purchase_order = picking.purchase_id
        if not purchase_order or not purchase_order.origin:
            return

        origin = purchase_order.origin
        origin_parts = [p.strip() for p in origin.split(',') if p.strip()]

        SaleOrder = self.env['sale.order']

        for part in origin_parts:
            sale_order = SaleOrder.search([('name', '=', part)], limit=1)
            if not sale_order or not sale_order.procurement_group_id:
                continue

            # Tìm phiếu lấy hàng (Pick) của SO
            target_picks = self.env['stock.picking'].search([
                ('group_id', '=', sale_order.procurement_group_id.id),
                ('state', 'in', ['confirmed', 'waiting', 'partially_available']),
                ('picking_type_id.sequence_code', '=', 'PICK'),
            ])
            if not target_picks:
                continue

            # Lấy sản phẩm + location cần giữ
            needed_moves = target_picks.move_ids.filtered(
                lambda m: m.state in ('confirmed', 'waiting', 'partially_available')
            )
            if not needed_moves:
                continue

            target_products = needed_moves.mapped('product_id')
            target_location = target_picks[0].location_id

            # Tìm phiếu KHÁC đang giữ hàng cùng sản phẩm tại cùng location
            other_pickings = self.env['stock.picking'].search([
                ('id', 'not in', target_picks.ids),
                ('state', 'in', ['assigned', 'partially_available']),
                ('location_id', '=', target_location.id),
            ])

            # Hủy giữ hàng từ phiếu khác cho sản phẩm cần ưu tiên
            unreserved_pickings = self.env['stock.picking']
            for other in other_pickings:
                conflicting = other.move_ids.filtered(
                    lambda m: m.product_id in target_products
                    and m.quantity > 0
                )
                if conflicting:
                    _logger.info(
                        'PO %s: Hủy giữ hàng từ %s để ưu tiên SO %s',
                        purchase_order.name, other.name, sale_order.name,
                    )
                    other.do_unreserve()
                    unreserved_pickings |= other

            # Giữ hàng CHO phiếu Pick của SO
            _logger.info(
                'PO %s (origin=%s): Giữ hàng cho SO %s - phiếu: %s',
                purchase_order.name, origin, sale_order.name,
                ', '.join(target_picks.mapped('name')),
            )
            target_picks.action_assign()

            # Assign lại phiếu đã bị hủy (lấy phần thừa nếu còn)
            if unreserved_pickings:
                unreserved_pickings.action_assign()
