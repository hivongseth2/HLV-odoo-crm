from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class StockBarcodeController(http.Controller):

    @http.route(['/warehouse_video_packaging/api/scan_pick'], type='json', auth='user', methods=['POST'])
    def scan_pick_and_pack(self, barcode):
        _logger.info(f"🔍 API POST: scan_pick_and_pack() Barcode={barcode}")

        picking = request.env['stock.picking'].sudo().search([('name', '=', barcode)], limit=1)
        if not picking:
            _logger.warning(f"❌ Không tìm thấy phiếu Picking với barcode: {barcode}")
            return {"error": "Picking not found"}

        if not picking.move_line_ids:
            _logger.warning(f"❌ Phiếu {picking.name} chưa có move line")
            return {"error": "No move line, please Pick first"}

        if picking.video_state == 'idle':
            _logger.info(f"🎥 BẮT ĐẦU pack & quay: {picking.name}")
            picking.action_put_in_pack()
            return {"status": "started", "picking": picking.name}

        _logger.info(f"ℹ️ Phiếu {picking.name} đang ở trạng thái: {picking.video_state}")
        return {"status": f"Already {picking.video_state}", "picking": picking.name}
