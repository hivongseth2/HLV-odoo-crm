from odoo import api, models
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.onchange('quantity')
    def _onchange_move_quantity_check_stock(self):
        """
        Khi user nhập tay vào cột 'SL thực' (stock.move.quantity) ở list view,
        kiểm tra tổng available tại location (bao gồm sub-locations).
        Chặn trước khi Odoo phân bổ ra move lines sai.
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
        total_reserved_others = sum(q.reserved_quantity for q in quants)

        # Số lượng move line hiện tại của move này đang giữ
        already_reserved_this_move = sum(
            ml.quantity for ml in self.move_line_ids
            if ml.state not in ['done', 'cancel']
        )

        # available = on_hand - reserved_by_others + reserved_by_this_move
        total_available = total_on_hand - total_reserved_others + already_reserved_this_move

        _logger.info(
            '[MOVE_QTY] onchange | product=%s | location=%s | '
            'on_hand=%s | reserved_others=%s | this_move_reserved=%s | '
            'total_available=%s | qty_entered=%s',
            self.product_id.display_name,
            self.location_id.display_name,
            total_on_hand,
            total_reserved_others,
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
                        'Sản phẩm "%s" chỉ còn %s cái khả dụng tại "%s".\n'
                        'Hệ thống đã điều chỉnh từ %s thành %s cái.\n\n'
                        'Tồn kho theo vị trí:\n%s'
                    ) % (
                        self.product_id.display_name,
                        total_available,
                        self.location_id.display_name,
                        old_qty,
                        self.quantity,
                        loc_details or '  (không có)',
                    )
                }
            }
