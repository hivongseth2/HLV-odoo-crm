from odoo import api, models
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_assign(self, assign_picking_ids=False):
        """
        Cải tiến logic assign - nếu assign bình thường fail,
        thử cách khác (create move line tay hoặc partial assign).
        """
        # Tìm moves không assign được
        failed_moves = self.env['stock.move']
        
        # Cố gắng assign bình thường trước
        try:
            result = super()._action_assign(assign_picking_ids)
        except Exception as e:
            _logger.warning(f"Assign bình thường fail: {str(e)[:100]}")
            result = None
        
        # Kiểm tra lại moves nào vẫn không assign được
        for move in self:
            if move.state not in ['assigned', 'partially_available', 'done']:
                # Cố gắng create move lines nếu chưa có
                if not move.move_line_ids and move.quantity_available > 0:
                    _logger.info(f"Auto-creating move line for {move.name}")
                    try:
                        self._auto_create_move_lines(move)
                    except Exception as e:
                        _logger.error(f"Lỗi auto-create move line: {str(e)[:100]}")
                        failed_moves |= move

        return result

    def _auto_create_move_lines(self, move):
        """
        Tự động tạo move line nếu move không có.
        Dùng khi assign normal không hoạt động.
        """
        move.ensure_one()

        if not move.product_id or not move.location_id:
            return False

        # Lấy quantity có sẵn
        available = self._get_available_qty(move)

        if available <= 0:
            _logger.warning(f"Không có stock available cho {move.name}")
            return False

        # Lấy qty cần assign
        qty_to_assign = min(move.product_uom_qty, available)

        # Tạo move line
        ml_vals = {
            'move_id': move.id,
            'product_id': move.product_id.id,
            'product_uom_id': move.product_uom.id,
            'location_id': move.location_id.id,
            'location_dest_id': move.location_dest_id.id,
            'company_id': move.company_id.id,
            'qty_done': 0,  # Chưa done, chỉ assigned
            'quantity': qty_to_assign,
        }

        try:
            self.env['stock.move.line'].create(ml_vals)
            _logger.info(f"Auto-created move line: {qty_to_assign} for {move.name}")
            
            # Update move state
            if qty_to_assign >= move.product_uom_qty:
                move.state = 'assigned'
            else:
                move.state = 'partially_available'
            
            return True
        except Exception as e:
            _logger.error(f"Failed to create move line: {str(e)}")
            return False

    def _get_available_qty(self, move):
        """
        Tính quantity available tại location.
        """
        move.ensure_one()

        if not move.product_id or not move.location_id:
            return 0.0

        # Cách 1: Dùng context location
        qty_1 = move.product_id.with_context({
            'location': move.location_id.id,
        }).qty_available

        if qty_1 > 0:
            return qty_1

        # Cách 2: Tìm quant tại location
        quant = self.env['stock.quant'].search([
            ('product_id', '=', move.product_id.id),
            ('location_id', '=', move.location_id.id),
        ], limit=1)

        if quant:
            return max(0, quant.available_quantity)

        return 0.0
