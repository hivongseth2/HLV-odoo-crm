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
        - Tự động giới hạn số lượng đến mức có sẵn tại vị trí
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

        # Lấy tồn kho thực tế TẠI VỊ TRÍ NÀY
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', self.location_id.id),
        ], limit=1)

        stock_at_location = quant.quantity if quant else 0.0
        reserved_at_location = quant.reserved_quantity if quant else 0.0
        available_at_location = quant.available_quantity if quant else 0.0

        # Số lượng line này đang giữ trước khi user chỉnh (0 nếu là line mới)
        original_qty = self._origin.quantity if self._origin else 0.0

        # Giới hạn thực = available (của đơn khác chưa dùng) + phần line này đang giữ
        max_allowed = available_at_location + original_qty

        _logger.info(
            '[QTY_LIMIT] Stock check | product=%s | location=%s | '
            'on_hand=%s | reserved=%s | available=%s | original_qty=%s | max_allowed=%s | qty_to_reserve=%s',
            self.product_id.display_name,
            self.location_id.display_name,
            stock_at_location,
            reserved_at_location,
            available_at_location,
            original_qty,
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
                        'Vị trí "%s" chỉ còn %s cái khả dụng (tồn kho: %s, đã giữ bởi đơn khác: %s).\n'
                        'Hệ thống đã tự động điều chỉnh từ %s thành %s cái.'
                    ) % (
                        self.location_id.display_name,
                        max_allowed,
                        stock_at_location,
                        reserved_at_location - original_qty,
                        old_qty,
                        self.quantity,
                    )
                }
            }

        _logger.info('[QTY_LIMIT] OK | qty=%s <= max_allowed=%s | no adjustment needed',
                     self.quantity, max_allowed)

    def _get_total_stock_at_location(self):
        """
        Lấy tồn kho thực tế (on-hand) tại vị trí.
        Bao gồm:
        - Sản phẩm có sẵn trong kho
        
        Returns:
            float: Số lượng có sẵn
        """
        self.ensure_one()

        if not self.product_id or not self.location_id:
            return 0.0

        # Tìm stock quant tại vị trí
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', self.location_id.id),
        ], limit=1)

        if quant:
            # Trả về quantity (số lượng thực tế)
            return max(0.0, quant.quantity)
        
        return 0.0

    def _get_reserved_qty_in_move(self):
        """
        Lấy tổng số lượng đã dành riêng trong move hiện tại (không tính dòng này).
        Chỉ tính số lượng từ dòng khác trong cùng move.
        
        Returns:
            float: Tổng số lượng đã dành riêng
        """
        self.ensure_one()

        if not self.move_id or not self.product_id or not self.location_id:
            return 0.0

        # Tìm tất cả dòng khác trong move này
        # Cùng sản phẩm + cùng vị trí + khác dòng hiện tại + chưa hoàn thành
        other_lines = self.env['stock.move.line'].search([
            ('move_id', '=', self.move_id.id),
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', self.location_id.id),
            ('id', '!=', self.id),  # Không tính dòng hiện tại
            ('state', 'not in', ['done', 'cancel']),
        ])

        # Tính tổng quantity của các dòng khác
        reserved = sum(line.quantity for line in other_lines)
        
        return max(0.0, reserved)
