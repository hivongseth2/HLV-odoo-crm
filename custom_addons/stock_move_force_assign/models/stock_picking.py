from odoo import api, models, _
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # NOTE: Không override action_assign vì conflict với hlv_priority_stock_reservation
    # Sử dụng debug tool thay vào đó để kiểm tra lỗi assign
    
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
