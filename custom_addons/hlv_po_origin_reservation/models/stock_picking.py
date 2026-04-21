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
        """Sau khi nhập kho, tìm SO từ PO.origin và giữ hàng cho đơn giao.
        Nếu PO không có origin hoặc origin không match SO nào,
        giữ hàng cho đơn bán hàng cũ nhất đang chờ (cùng warehouse). mới
        """
        purchase_order = picking.purchase_id
        # Lấy danh sách sản phẩm vừa nhập kho
        incoming_product_ids = picking.move_ids.filtered(
            lambda m: m.state == 'done'
        ).mapped('product_id').ids

        if not incoming_product_ids:
            return

        reserved = False
        origin = (purchase_order.origin or '').strip() if purchase_order else ''

        if origin:
            # Case 1: Có origin → thử giữ hàng cho SO tương ứng
            reserved = self._reserve_by_origin(purchase_order, incoming_product_ids)

        if not reserved:
            # Case 2: Không có origin HOẶC origin không match SO nào
            # → giữ hàng cho SO cũ nhất đang chờ (cùng warehouse)
            self._reserve_for_oldest_waiting_so(picking, incoming_product_ids)

    def _reserve_by_origin(self, purchase_order, incoming_product_ids):
        """Giữ hàng cho SO được chỉ định trong PO.origin.
        Return True nếu đã tìm và reserve thành công ít nhất 1 SO.
        """
        origin = purchase_order.origin
        origin_parts = [p.strip() for p in origin.split(',') if p.strip()]

        SaleOrder = self.env['sale.order']
        reserved_any = False

        for part in origin_parts:
            sale_order = SaleOrder.search([('name', '=', part)], limit=1)
            if not sale_order or not sale_order.procurement_group_id:
                continue

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
                reserved_any = True

        return reserved_any

    def _reserve_for_oldest_waiting_so(self, picking, incoming_product_ids):
        """Không có origin hoặc origin không match →
        tìm các SO cũ nhất đang chờ hàng (cùng warehouse, có sản phẩm trùng)
        và giữ hàng theo thứ tự cũ nhất trước.
        """
        # Xác định warehouse của phiếu nhập kho để chỉ reserve cùng kho
        warehouse = picking.picking_type_id.warehouse_id

        domain = [
            ('picking_type_code', '=', 'outgoing'),
            ('state', 'in', ['confirmed', 'waiting', 'partially_available']),
        ]
        if warehouse:
            domain.append(('picking_type_id.warehouse_id', '=', warehouse.id))

        waiting_pickings = self.env['stock.picking'].search(
            domain, order='scheduled_date asc, id asc',
        )

        # Lọc những picking có sản phẩm trùng với hàng vừa nhập
        incoming_product_set = set(incoming_product_ids)
        pickings_to_reserve = waiting_pickings.filtered(
            lambda p: bool(
                set(p.move_ids.filtered(
                    lambda m: m.state not in ('done', 'cancel')
                ).mapped('product_id').ids) & incoming_product_set
            )
        )

        if pickings_to_reserve:
            _logger.info(
                'Nhập kho %s (fallback): Giữ hàng cho %d phiếu giao cũ nhất (warehouse %s): %s',
                picking.name,
                len(pickings_to_reserve),
                warehouse.name if warehouse else 'all',
                ', '.join(pickings_to_reserve.mapped('name')),
            )
            # Gọi action_assign theo thứ tự để ưu tiên đơn cũ nhất
            for p in pickings_to_reserve:
                p.action_assign()
