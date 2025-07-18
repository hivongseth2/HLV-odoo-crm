from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class BarcodeControllerOverride(http.Controller):

    @http.route('/stock_barcode/get_barcode_data', type='json', auth='user')
    def get_barcode_data(self, model, res_id, **kwargs):
        """Override GET_BARCODE_DATA to auto-switch if current picking is done."""
        if model == "stock.picking":
            picking = request.env[model].sudo().browse(res_id)
            if picking.exists() and picking.state == "done" and picking.group_id:
                _logger.info(f"[AUTO-NEXT] Phiếu {picking.name} đã hoàn tất. Tìm phiếu tiếp theo...")
                next_picking = request.env[model].sudo().search([
                    ('group_id', '=', picking.group_id.id),
                    ('id', '!=', picking.id),
                    ('state', 'not in', ['done', 'cancel'])
                ], order='scheduled_date asc', limit=1)
                if next_picking:
                    res_id = next_picking.id
                    _logger.info(f"[AUTO-NEXT] Chuyển sang phiếu: {next_picking.name}")

        # Gọi lại logic gốc của Odoo (nếu cần)
        return request.env['ir.actions.client']._stock_barcode_data(model, res_id)
