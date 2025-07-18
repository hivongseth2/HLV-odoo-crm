import logging
from odoo import models, api

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def _get_barcode_data(self, barcode):
        _logger.info("🚀 [BarcodePatch] Bắt đầu xử lý barcode: %s", barcode)

        # Tìm phiếu theo barcode
        picking = self.search([('name', '=', barcode)], limit=1)
        if not picking:
            _logger.warning("❌ [BarcodePatch] Không tìm thấy phiếu nào có mã: %s", barcode)
            return super()._get_barcode_data(barcode)

        _logger.info("🔍 [BarcodePatch] Tìm thấy phiếu: %s (state=%s)", picking.name, picking.state)

        # Nếu phiếu đã done → tìm phiếu tiếp theo cùng group
        if picking.state == 'done' and picking.group_id:
            _logger.info("✅ [BarcodePatch] Phiếu %s đã DONE. Tìm phiếu kế tiếp trong group: %s",
                         picking.name, picking.group_id.display_name)

            next_picking = self.search([
                ('group_id', '=', picking.group_id.id),
                ('id', '!=', picking.id),
                ('state', 'not in', ['done', 'cancel']),
            ], order='scheduled_date asc', limit=1)

            if next_picking:
                _logger.info("➡️ [BarcodePatch] Nhảy sang phiếu tiếp theo: %s", next_picking.name)
                picking = next_picking
            else:
                _logger.info("✅ [BarcodePatch] Không có phiếu kế tiếp. Giữ lại phiếu cũ.")

        else:
            _logger.info("🟡 [BarcodePatch] Phiếu chưa hoàn tất hoặc không thuộc group.")

        # Gọi hàm gốc để trả về dữ liệu giao diện
        _logger.info("📤 [BarcodePatch] Trả dữ liệu về cho phiếu: %s", picking.name)
        return super()._get_barcode_data(picking.name)
