from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class StockBarcodePatchedController(http.Controller):

    @http.route('/stock_barcode/get_barcode_data', type='json', auth='user')
    def get_barcode_data(self, barcode):
        _logger.info("🧠 [Patch] Nhận mã barcode: %s", barcode)

        Picking = request.env['stock.picking'].sudo()
        picking = Picking.search([('name', '=', barcode)], limit=1)

        if picking and picking.state == 'done' and picking.group_id:
            _logger.info("📦 Phiếu %s đã DONE. Tìm phiếu tiếp theo trong group %s",
                         picking.name, picking.group_id.name)

            next_picking = Picking.search([
                ('group_id', '=', picking.group_id.id),
                ('id', '!=', picking.id),
                ('state', 'not in', ['done', 'cancel']),
            ], order='scheduled_date asc', limit=1)

            if next_picking:
                _logger.info("➡️ Nhảy sang phiếu mới: %s", next_picking.name)
                picking = next_picking
            else:
                _logger.info("✅ Không có phiếu nào khác trong group.")

        elif not picking:
            _logger.warning("❌ Không tìm thấy phiếu có mã: %s", barcode)

        return Picking._get_barcode_data(picking.name if picking else barcode)
