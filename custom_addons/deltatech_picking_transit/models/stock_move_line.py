from odoo import api, models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    @api.constrains("location_id", "location_dest_id")
    def _check_hlv_no_transit(self):
        """Chặn sửa tay vị trí Transit / đích ngoài CHUYENKHO (chuyển sang kho khác) trên từng dòng; vị trí trùng với phiếu đã do ràng buộc phiếu xử lý
        (để phiếu Transit cũ vẫn giữ chỗ/xác nhận được)."""
        for line in self.filtered("picking_id"):
            picking = line.picking_id
            picking._hlv_check_no_transit(
                (line.location_id | line.location_dest_id) - (picking.location_id | picking.location_dest_id)
            )
            picking._hlv_check_inter_warehouse_dest(line.location_dest_id)
