from odoo import api, models, fields
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.onchange('quantity')
    def _onchange_quantity_check_stock(self):
        """
        Kiểm tra số lượng dành riêng so với tồn kho thực tế khi thay đổi.
        - Chỉ áp dụng cho kho nội bộ (internal locations)
        - Bỏ qua các moves đã hoàn thành
        - Tự động giới hạn số lượng đến mức có sẵn
        """
        if not self.location_id or not self.product_id:
            return

        # Chỉ kiểm tra kho nội bộ
        if self.location_id.usage != 'internal':
            return

        # Bỏ qua moves đã hoàn thành hoặc hủy
        if self.move_id and self.move_id.state in ['done', 'cancel']:
            return

        # Lấy tồn kho thực tế tại vị trí
        total_stock = self._get_total_stock_at_location()

        # Lấy số lượng đã dành riêng khác (không tính dòng này)
        reserved_qty = self._get_reserved_qty_in_move()

        # Số lượng còn available = tồn kho - số đã dành riêng + số của dòng hiện tại
        available_qty = total_stock - reserved_qty

        # Nếu số lượng nhập vào vượt quá có sẵn, điều chỉnh lại
        if self.quantity > available_qty:
            old_qty = self.quantity
            self.quantity = available_qty

            # Hiển thị cảnh báo
            return {
                'warning': {
                    'title': _('Vượt quá tồn kho!'),
                    'message': _(
                        'Bạn cố gắng dành riêng %s cái, nhưng chỉ còn %s cái khả dụng tại vị trí "%s".\n'
                        'Hệ thống đã tự động điều chỉnh thành %s cái.'
                    ) % (
                        old_qty,
                        available_qty,
                        self.location_id.display_name,
                        available_qty
                    )
                }
            }

    @api.constrains('quantity', 'location_id', 'product_id')
    def _check_quantity_not_exceed_stock(self):
        """
        Ràng buộc cấp database để ngăn lưu số lượng vượt quá tồn kho.
        Đảm bảo kiểm tra khi dùng API hoặc bulk operations.
        """
        for record in self:
            # Bỏ qua các dòng không có đủ thông tin
            if not record.product_id or not record.location_id:
                continue

            # Chỉ kiểm tra kho nội bộ
            if record.location_id.usage != 'internal':
                continue

            # Bỏ qua moves đã hoàn thành hoặc hủy
            if record.move_id and record.move_id.state in ['done', 'cancel']:
                continue

            # Lấy tồn kho thực tế
            total_stock = record._get_total_stock_at_location()
            
            # Lấy số lượng đã dành riêng khác trong move này
            reserved_qty = record._get_reserved_qty_in_move()
            
            # Tính số lượng có sẵn
            available_qty = total_stock - reserved_qty

            # Kiểm tra ràng buộc
            if record.quantity > available_qty:
                raise models.ValidationError(
                    _('Không thể dành riêng %s cái của "%s" tại vị trí "%s".\n'
                      'Chỉ còn %s cái khả dụng.\n'
                      'Vị trí: %s') % (
                        record.quantity,
                        record.product_id.display_name,
                        record.location_id.display_name,
                        available_qty,
                        record.location_id.display_name
                    )
                )


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
