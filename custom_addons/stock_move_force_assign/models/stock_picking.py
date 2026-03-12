from odoo import api, models, _
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_assign(self):
        """
        Override action_assign để thêm fallback logic.
        Nếu assign thất bại, ghi log chi tiết.
        """
        _logger.info(f"=== Picking {self.name} - action_assign START ===")
        
        for move in self.move_ids:
            _logger.info(
                f"Move {move.name}: qty={move.product_uom_qty}, "
                f"state={move.state}, available={self._get_move_qty_available(move)}"
            )

        # Cố gắng assign normal
        try:
            result = super().action_assign()
            _logger.info(f"✅ {self.name} - Assign thành công")
            return result
        except Exception as e:
            _logger.error(f"❌ {self.name} - Assign fail: {str(e)}")
            
            # Fallback: Thử assign từng move
            _logger.info(f"Fallback: Assign từng move...")
            for move in self.move_ids.filtered(lambda m: m.state not in ['assigned', 'partially_available', 'done']):
                try:
                    move._action_assign()
                    _logger.info(f"  ✅ {move.name} assigned")
                except Exception as move_error:
                    _logger.warning(f"  ⚠️  {move.name} failed: {str(move_error)[:100]}")

        _logger.info(f"=== Picking {self.name} - action_assign END ===")
        return True

    def _get_move_qty_available(self, move):
        """
        Tính qty available cho 1 move.
        """
        if not move.product_id or not move.location_id:
            return 0

        quant = self.env['stock.quant'].search([
            ('product_id', '=', move.product_id.id),
            ('location_id', '=', move.location_id.id),
        ], limit=1)

        if quant:
            return quant.available_quantity
        return 0
