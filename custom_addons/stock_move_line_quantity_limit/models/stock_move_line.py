from odoo import api, models, fields
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.onchange('quantity')
    def _onchange_quantity_check_stock(self):
        """
        Kiểm tra số lượng nhập tay không vượt quá tồn kho KHẢ DỤNG tại vị trí.
        
        Công thức:
          max_allowed = available_quantity + current_line_holding
        
        - available_quantity: quant.quantity - quant.reserved_quantity (tính từ quant, ổn định)
        - current_line_holding: phần mà line này ĐÃ giữ trước (từ _origin, 0 cho line mới)
        
        Cách này tránh query move_lines (NewId/False bug) mà vẫn tính đúng đơn khác đang giữ.
        """
        if not self.location_id or not self.product_id:
            return
        if self.location_id.usage != 'internal':
            return
        if self.move_id and self.move_id.state in ['done', 'cancel']:
            return

        # Tồn kho tại location + sub-locations
        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', 'child_of', self.location_id.id),
        ])
        total_on_hand = sum(q.quantity for q in quants)
        total_available = sum(q.available_quantity for q in quants)

        # Phần mà line này đã giữ trước khi user chỉnh (0 nếu line mới)
        current_holding = 0.0
        if self._origin and isinstance(self._origin.id, int):
            current_holding = self._origin.quantity or 0.0

        # max = hàng chưa ai giữ + phần line này đã giữ sẵn
        max_allowed = total_available + current_holding

        _logger.info(
            '[QTY_LIMIT] onchange | product=%s | location=%s (id=%s) | '
            'on_hand=%s | available=%s | current_holding=%s | max_allowed=%s | qty_entered=%s',
            self.product_id.display_name,
            self.location_id.display_name,
            self.location_id.id,
            total_on_hand,
            total_available,
            current_holding,
            max_allowed,
            self.quantity,
        )

        if self.quantity > max_allowed:
            old_qty = self.quantity
            self.quantity = max(0.0, max_allowed)

            _logger.warning(
                '[QTY_LIMIT] BLOCKED | product=%s | location=%s | '
                'qty_entered=%s | max_allowed=%s | adjusted_to=%s',
                self.product_id.display_name,
                self.location_id.display_name,
                old_qty,
                max_allowed,
                self.quantity,
            )

            return {
                'warning': {
                    'title': _('Vượt quá tồn kho tại vị trí!'),
                    'message': _(
                        'Vị trí "%s" chỉ còn %s cái khả dụng '
                        '(tồn kho: %s, đã giữ bởi đơn khác: %s).\n'
                        'Hệ thống đã tự động điều chỉnh từ %s thành %s cái.'
                    ) % (
                        self.location_id.display_name,
                        max_allowed,
                        total_on_hand,
                        total_on_hand - total_available - current_holding,
                        old_qty,
                        self.quantity,
                    )
                }
            }
