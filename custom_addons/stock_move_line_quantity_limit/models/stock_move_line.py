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
        if not self.location_id or not self.product_id:
            return

        # Chỉ kiểm tra kho nội bộ
        if self.location_id.usage != 'internal':
            return

        # Bỏ qua moves đã hoàn thành hoặc hủy
        if self.move_id and self.move_id.state in ['done', 'cancel']:
            return

        # Lấy tồn kho thực tế TẠI VỊ TRÍ NÀY
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', self.location_id.id),
        ], limit=1)

        stock_at_location = quant.quantity if quant else 0.0

        # Nếu số lượng nhập vào vượt quá tồn kho tại vị trí, điều chỉnh lại
        if self.quantity > stock_at_location:
            old_qty = self.quantity
            self.quantity = max(0.0, stock_at_location)

            return {
                'warning': {
                    'title': _('Vượt quá tồn kho tại vị trí!'),
                    'message': _(
                        'Vị trí "%s" chỉ còn %s cái.\n'
                        'Hệ thống đã tự động điều chỉnh từ %s thành %s cái.'
                    ) % (
                        self.location_id.display_name,
                        stock_at_location,
                        old_qty,
                        stock_at_location
                    )
                }
            }

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
