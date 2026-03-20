from odoo import api, models, fields
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.onchange('quantity', 'location_id')
    def _onchange_quantity_check_stock(self):
        """
        Kiểm tra số lượng nhập tay không vượt quá tồn kho KHẢ DỤNG tại vị trí.
        
        Công thức:
          max_allowed = available_quantity + current_line_holding
        
        Lấy location chính xác:
          - Line cũ: _origin.location_id (DB ground truth)
          - Line mới: self.location_id, fallback move_id.location_id
        """
        if not self.product_id:
            return
        if self.move_id and self.move_id.state in ['done', 'cancel']:
            return

        # --- Xác định location chính xác ---
        location = False
        is_existing_line = self._origin and isinstance(self._origin.id, int)

        if is_existing_line:
            # Line cũ: _origin.location_id là giá trị thực từ DB, không bị ảnh hưởng bởi form
            location = self._origin.location_id
        
        if not location and self.location_id:
            location = self.location_id

        if not location and self.move_id and self.move_id.location_id:
            location = self.move_id.location_id

        if not location or location.usage != 'internal':
            return

        # Nếu location là parent (có child locations), Odoo có thể đang truyền sai location
        # vào onchange context (truyền location cha thay vì sub-location mà user chọn).
        # Bỏ qua validation để tránh block nhầm — khi user chọn đúng leaf location,
        # onchange sẽ fire lại với location chính xác.
        if location.child_ids:
            _logger.info(
                '[QTY_LIMIT] SKIP - parent location (has children): %s (id=%s). '
                'Waiting for leaf location selection.',
                location.display_name, location.id,
            )
            return

        # Tồn kho tại location + sub-locations (child_of để bao gồm trường hợp leaf có sub-bin)
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

        # max = hàng chưa ai giữ + phần line này đã giữ sẵn
        max_allowed = total_available + current_holding

        _logger.info(
            '[QTY_LIMIT] onchange | product=%s | location=%s (id=%s) | '
            'form_location=%s (id=%s) | origin_location=%s | '
            'on_hand=%s | available=%s | current_holding=%s | max_allowed=%s | qty_entered=%s',
            self.product_id.display_name,
            location.display_name,
            location.id,
            self.location_id.display_name if self.location_id else 'N/A',
            self.location_id.id if self.location_id else 'N/A',
            self._origin.location_id.display_name if is_existing_line and self._origin.location_id else 'N/A',
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
