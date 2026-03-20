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
        
        Dùng self.location_id (có thể là parent) với child_of query để cover tất cả sub-locations.
        Nếu Odoo truyền parent trong onchange, child_of vẫn tính đúng tổng available.
        """
        if not self.product_id:
            return
        if self.move_id and self.move_id.state in ['done', 'cancel']:
            return

        # Lấy location — ưu tiên self.location_id (form), fallback _origin (DB), fallback move
        is_existing_line = self._origin and isinstance(self._origin.id, int)
        location = self.location_id
        if not location and is_existing_line:
            location = self._origin.location_id
        if not location and self.move_id:
            location = self.move_id.location_id

        if not location or location.usage != 'internal':
            return

        # Tồn kho tại location + sub-locations (child_of cover cả sub-bin)
        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', 'child_of', location.id),
        ])
        total_on_hand = sum(q.quantity for q in quants)
        total_available = sum(q.available_quantity for q in quants)

        # Phần mà line này đã giữ trước khi user chỉnh (0 nếu line mới)
        current_holding = 0.0
        if is_existing_line:
            current_holding = self._origin.quantity or 0.0

        # Phần mà MOVE này đang giữ trong DB tại location này (các line khác của cùng move)
        # Lý do cần: khi user xóa line cũ + thêm line mới trong cùng form chưa save,
        # DB vẫn còn reservation cũ → available = 0 → bị block oan.
        # Giải pháp: available = 0 (do move này giữ) + move_db_holding = 4 → max = 4
        move_db_holding = 0.0
        move_id_int = None
        if self.move_id:
            mid = self.move_id.id
            # Với line mới trong one2many dialog, move_id.id có thể là virtual NewId
            # → dùng _origin để lấy real DB id
            if not isinstance(mid, int) and self.move_id._origin:
                mid = self.move_id._origin.id
            if isinstance(mid, int):
                move_id_int = mid
        if move_id_int:
            sibling_lines = self.env['stock.move.line'].search([
                ('move_id', '=', move_id_int),
                ('product_id', '=', self.product_id.id),
                ('location_id', 'child_of', location.id),
                ('state', 'not in', ['done', 'cancel']),
            ])
            # Loại trừ chính line đang edit (đã tính trong current_holding)
            if is_existing_line:
                sibling_lines = sibling_lines.filtered(lambda l: l.id != self._origin.id)
            move_db_holding = sum(l.quantity for l in sibling_lines)

        # max = khả dụng + phần line này giữ + phần move này giữ trong DB
        # Công thức đúng cho cả: edit line cũ / delete+recreate / cross-order block
        max_allowed = total_available + current_holding + move_db_holding

        _logger.info(
            '[QTY_LIMIT] onchange | product=%s | location=%s (id=%s) | '
            'on_hand=%s | available=%s | current_holding=%s | move_db_holding=%s | max_allowed=%s | qty_entered=%s',
            self.product_id.display_name,
            location.display_name,
            location.id,
            total_on_hand,
            total_available,
            current_holding,
            move_db_holding,
            max_allowed,
            self.quantity,
        )

        if self.quantity > max_allowed:
            old_qty = self.quantity

            if max_allowed <= 0.0:
                # Không có hàng khả dụng — xóa line luôn thay vì để qty=0
                _logger.warning(
                    '[QTY_LIMIT] DELETE LINE | product=%s | location=%s | no stock available',
                    self.product_id.display_name, location.display_name,
                )
                # Đánh dấu để Odoo xóa line khỏi one2many
                if hasattr(self, '_origin') and isinstance(getattr(self._origin, 'id', None), int):
                    self._origin.unlink()
                else:
                    # Line mới chưa save — set virtual flag để UI loại bỏ
                    self.quantity = 0.0

                return {
                    'warning': {
                        'title': _('Không có tồn kho tại vị trí!'),
                        'message': _(
                            'Vị trí "%s" không còn hàng khả dụng '
                            '(tồn kho: %s, đã giữ bởi đơn khác: %s).\n'
                            'Dòng đã bị xóa tự động.'
                        ) % (
                            location.display_name,
                            total_on_hand,
                            total_on_hand - move_db_holding,
                        )
                    }
                }

            self.quantity = max_allowed

            _logger.warning(
                '[QTY_LIMIT] BLOCKED | product=%s | location=%s | '
                'qty_entered=%s | max_allowed=%s | adjusted_to=%s',
                self.product_id.display_name,
                location.display_name,
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
                        location.display_name,
                        max_allowed,
                        total_on_hand,
                        total_on_hand - total_available - current_holding,
                        old_qty,
                        self.quantity,
                    )
                }
            }
