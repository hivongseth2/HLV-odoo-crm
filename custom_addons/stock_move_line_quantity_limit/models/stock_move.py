from odoo import api, models
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _get_cross_picking_pending_done(self, product, location):
        """
        Tính tổng qty đã nhập tay từ CÁC PICKING KHÁC cùng product + location
        mà CHƯA phản ánh trong quant.reserved_quantity.

        Logic đơn giản:
        1. Tìm tất cả move lines cùng product/location, chưa done/cancel, qty > 0
        2. Sum qty của các picking KHÁC
        3. Trừ đi phần đã reserved trong quant (vì phần đó đã tính rồi)
        → Kết quả = phần "ảo" chưa reserve nhưng user đã nhập tay
        """
        current_picking_id = self.picking_id.id if self.picking_id else False

        # Lấy tất cả move lines hợp lệ
        all_pending_lines = self.env['stock.move.line'].search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
            ('state', 'not in', ['done', 'cancel']),
            ('quantity', '>', 0),
        ])

        # Tổng qty từ các picking KHÁC
        other_picking_qty = sum(
            ml.quantity for ml in all_pending_lines
            if ml.picking_id.id != current_picking_id
        )

        # Lấy tổng reserved_quantity trong quant (đây là phần ĐÃ được reserve chính thức)
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
        ])
        total_quant_reserved = sum(q.reserved_quantity for q in quants)

        # Phần pending = qty picking khác - phần đã reserve trong quant
        # (vì phần reserve đã bị trừ bởi available_quantity rồi)
        # Nếu kết quả < 0 → tất cả đã được reserve → pending = 0
        pending = max(0.0, other_picking_qty - total_quant_reserved)

        _logger.info(
            '[CROSS_PICK] product=%s | location=%s | other_picking_qty=%s | '
            'quant_reserved=%s | pending_unreserved=%s',
            product.display_name, location.display_name,
            other_picking_qty, total_quant_reserved, pending,
        )

        return pending

    @api.onchange('quantity')
    def _onchange_move_quantity_check_stock(self):
        """
        Khi user nhập tay vào cột 'SL thực' (stock.move.quantity) ở list view,
        kiểm tra tổng available tại location (bao gồm sub-locations).
        Tính cả pending done qty từ các picking khác chưa validate.
        """
        if not self.location_id or not self.product_id:
            return

        if self.location_id.usage != 'internal':
            return

        if self.state in ['done', 'cancel']:
            return

        # Tổng available tại location này và tất cả sub-locations
        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', 'child_of', self.location_id.id),
        ])

        total_on_hand = sum(q.quantity for q in quants)
        total_reserved_in_quant = sum(q.reserved_quantity for q in quants)

        # Số lượng move line hiện tại của move này đang giữ
        already_reserved_this_move = sum(
            ml.quantity for ml in self.move_line_ids
            if ml.state not in ['done', 'cancel']
        )

        # Pending done qty từ các picking KHÁC (chưa phản ánh trong quant.reserved)
        pending_done_others = self._get_cross_picking_pending_done(
            self.product_id, self.location_id
        )

        # available = on_hand - reserved_in_quant - pending_others + this_move_reserved
        total_available = (
            total_on_hand
            - total_reserved_in_quant
            - pending_done_others
            + already_reserved_this_move
        )

        _logger.info(
            '[MOVE_QTY] onchange | product=%s | location=%s | '
            'on_hand=%s | reserved_in_quant=%s | pending_done_others=%s | '
            'this_move_reserved=%s | total_available=%s | qty_entered=%s',
            self.product_id.display_name,
            self.location_id.display_name,
            total_on_hand,
            total_reserved_in_quant,
            pending_done_others,
            already_reserved_this_move,
            total_available,
            self.quantity,
        )

        if self.quantity > total_available:
            old_qty = self.quantity
            self.quantity = max(0.0, total_available)

            _logger.warning(
                '[MOVE_QTY] BLOCKED | product=%s | qty_entered=%s | max_available=%s | adjusted_to=%s',
                self.product_id.display_name, old_qty, total_available, self.quantity,
            )

            # Breakdown per location để user biết hàng ở đâu
            loc_details = '\n'.join(
                '  • %s: %s cái' % (q.location_id.display_name, q.available_quantity)
                for q in quants if q.quantity > 0
            )

            return {
                'warning': {
                    'title': _('Vượt quá tồn kho khả dụng!'),
                    'message': _(
                        'Sản phẩm "%s" chỉ còn %s cái khả dụng thực tế tại "%s".\n'
                        'Tồn kho: %s | Đã giữ (quant): %s | Đang chờ ở đơn khác: %s\n'
                        'Hệ thống đã điều chỉnh từ %s thành %s cái.\n\n'
                        'Tồn kho theo vị trí:\n%s'
                    ) % (
                        self.product_id.display_name,
                        total_available,
                        self.location_id.display_name,
                        total_on_hand,
                        total_reserved_in_quant,
                        pending_done_others,
                        old_qty,
                        self.quantity,
                        loc_details or '  (không có)',
                    )
                }
            }

    def write(self, vals):
        """
        Server-side validation: khi save move với quantity thay đổi,
        kiểm tra cross-picking availability.
        """
        res = super().write(vals)

        if 'quantity' in vals and not self.env.context.get('skip_qty_limit_write_check'):
            for move in self:
                if not move.product_id or not move.location_id:
                    continue
                if move.location_id.usage != 'internal':
                    continue
                if move.state in ['done', 'cancel']:
                    continue

                qty_done = move.quantity
                if qty_done <= 0:
                    continue

                # Tính real available
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', move.product_id.id),
                    ('location_id', 'child_of', move.location_id.id),
                ])
                total_on_hand = sum(q.quantity for q in quants)
                total_reserved = sum(q.reserved_quantity for q in quants)

                # Pending done từ MỌI picking khác (phần chưa reserve trong quant)
                pending_others = move._get_cross_picking_pending_done(
                    move.product_id, move.location_id
                )

                # Real available = on_hand - quant_reserved - pending_unreserved_others
                real_available = total_on_hand - total_reserved - pending_others

                if qty_done > real_available and real_available >= 0:
                    adjusted = max(0.0, real_available)
                    _logger.warning(
                        '[MOVE_QTY] WRITE ADJUST | product=%s | picking=%s | '
                        'qty_done=%s > real_available=%s | adjusted_to=%s',
                        move.product_id.display_name,
                        move.picking_id.name if move.picking_id else 'N/A',
                        qty_done, real_available, adjusted,
                    )
                    # Dùng super().write để tránh đệ quy
                    super(StockMove, move).write({'quantity': adjusted})

        return res
