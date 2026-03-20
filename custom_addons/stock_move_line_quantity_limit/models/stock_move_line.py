from odoo import api, models, fields
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.onchange('quantity')
    def _onchange_quantity_check_stock(self):
        """
        Kiểm tra số lượng nhập tay không vượt quá tồn kho TẠI VỊ TRÍ ĐÓ.
        - Chỉ áp dụng cho kho nội bộ (internal locations)
        - Bỏ qua các moves đã hoàn thành
        - Tính cả done qty từ picking khác chưa validate
        - Tự động giới hạn số lượng đến mức có sẵn tại vị trí

        Công thức: max_allowed = on_hand_at_loc - other_pickings_done_at_loc
        KHÔNG dùng quant.reserved_quantity (dễ bị ghost reservation).
        """
        _logger.info(
            '[QTY_LIMIT] onchange trigger | product=%s (id=%s) | location=%s (id=%s) | qty_entered=%s',
            self.product_id.display_name if self.product_id else 'N/A',
            self.product_id.id if self.product_id else 'N/A',
            self.location_id.display_name if self.location_id else 'N/A',
            self.location_id.id if self.location_id else 'N/A',
            self.quantity,
        )

        if not self.location_id or not self.product_id:
            _logger.info('[QTY_LIMIT] SKIP: missing location or product')
            return

        # Chỉ kiểm tra kho nội bộ
        if self.location_id.usage != 'internal':
            _logger.info('[QTY_LIMIT] SKIP: location usage=%s (not internal)', self.location_id.usage)
            return

        # Bỏ qua moves đã hoàn thành hoặc hủy
        if self.move_id and self.move_id.state in ['done', 'cancel']:
            _logger.info('[QTY_LIMIT] SKIP: move state=%s', self.move_id.state)
            return

        # Lấy tồn kho vật lý TẠI VỊ TRÍ NÀY và sub-locations (on-hand)
        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', 'child_of', self.location_id.id),
        ])
        stock_at_location = sum(q.quantity for q in quants)

        # Tìm move ID thực (dùng _origin.id để lấy DB id, bền hơn trong onchange)
        current_move_id = self._origin.move_id.id if self._origin and self._origin.move_id else (
            self.move_id.id if self.move_id else False
        )

        # Tổng done qty từ CÁC MOVE KHÁC tại cùng location (child_of)
        other_lines = self.env['stock.move.line'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', 'child_of', self.location_id.id),
            ('state', 'not in', ['done', 'cancel']),
            ('quantity', '>', 0),
            ('move_id', '!=', current_move_id),
        ])
        other_done = sum(oml.quantity for oml in other_lines)

        # Tổng done qty từ CÁC LINE KHÁC CÙNG MOVE tại cùng location
        # (trừ line hiện tại để không double count)
        current_line_origin_id = self._origin.id if self._origin else 0
        same_move_other_lines = self.env['stock.move.line'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', 'child_of', self.location_id.id),
            ('state', 'not in', ['done', 'cancel']),
            ('quantity', '>', 0),
            ('move_id', '=', current_move_id),
            ('id', '!=', current_line_origin_id),
        ])
        same_picking_other_done = sum(oml.quantity for oml in same_move_other_lines)

        # max_allowed = tồn kho vật lý - đơn khác - cùng move (line khác)
        max_allowed = stock_at_location - other_done - same_picking_other_done

        _logger.info(
            '[QTY_LIMIT] Stock check | product=%s | location=%s | '
            'on_hand=%s | other_moves_done=%s | same_move_other=%s | '
            'max_allowed=%s | qty_entered=%s',
            self.product_id.display_name,
            self.location_id.display_name,
            stock_at_location,
            other_done,
            same_picking_other_done,
            max_allowed,
            self.quantity,
        )

        # Nếu số lượng nhập vào vượt quá giới hạn, điều chỉnh lại
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
                        '(tồn kho: %s, đang giữ bởi đơn khác: %s).\n'
                        'Hệ thống đã tự động điều chỉnh từ %s thành %s cái.'
                    ) % (
                        self.location_id.display_name,
                        max(0.0, max_allowed),
                        stock_at_location,
                        other_done,
                        old_qty,
                        self.quantity,
                    )
                }
            }

        _logger.info('[QTY_LIMIT] OK | qty=%s <= max_allowed=%s | no adjustment needed',
                     self.quantity, max_allowed)
