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
        - Tính cả pending done qty từ picking khác chưa validate
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

        # Pending done qty từ các PICKING KHÁC tại cùng location này
        # (chưa phản ánh trong quant.reserved_quantity)
        current_picking_id = self.picking_id.id if self.picking_id else (
            self.move_id.picking_id.id if self.move_id and self.move_id.picking_id else False
        )
        other_pending_lines = self.env['stock.move.line'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', self.location_id.id),
            ('state', 'not in', ['done', 'cancel']),
            ('quantity', '>', 0),
        ])
        # Tổng qty từ picking khác
        other_picking_qty = sum(
            oml.quantity for oml in other_pending_lines
            if oml.picking_id.id != current_picking_id
        )
        # Pending = phần chưa reserve = other_qty - quant_reserved
        # (quant_reserved đã bị trừ qua available_at_location rồi)
        pending_done_others = max(0.0, other_picking_qty - reserved_at_location)

        # Giới hạn thực = available (của đơn khác chưa dùng) + phần line này đang giữ - pending_others
        max_allowed = available_at_location + original_qty - pending_done_others

        _logger.info(
            '[QTY_LIMIT] Stock check | product=%s | location=%s | '
            'on_hand=%s | reserved=%s | available=%s | original_qty=%s | '
            'pending_done_others=%s | max_allowed=%s | qty_to_reserve=%s',
            self.product_id.display_name,
            self.location_id.display_name,
            stock_at_location,
            reserved_at_location,
            available_at_location,
            original_qty,
            pending_done_others,
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
                        'Vị trí "%s" chỉ còn %s cái khả dụng thực tế '
                        '(tồn kho: %s, đã giữ: %s, đang chờ đơn khác: %s).\n'
                        'Hệ thống đã tự động điều chỉnh từ %s thành %s cái.'
                    ) % (
                        self.location_id.display_name,
                        max(0.0, max_allowed),
                        stock_at_location,
                        reserved_at_location - original_qty,
                        pending_done_others,
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
