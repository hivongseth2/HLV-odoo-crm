from odoo import api, models
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    # NOTE: Không override _action_assign vì gây conflict với Odoo base
    # Debug issues bằng stock_picking_debug.py thay vào đó
    
    def _get_available_qty_at_location(self, product_id, location_id):
        """
        Tính quantity available tại location.
        Helper function cho debug hoặc external use.
        """
        if not product_id or not location_id:
            return 0.0

        # Cách 1: Dùng context location
        qty_1 = product_id.with_context({
            'location': location_id.id,
        }).qty_available

        if qty_1 > 0:
            return qty_1

        # Cách 2: Tìm quant tại location
        quant = self.env['stock.quant'].search([
            ('product_id', '=', product_id.id),
            ('location_id', '=', location_id.id),
        ], limit=1)

        if quant:
            return max(0, quant.available_quantity)

        return 0.0
