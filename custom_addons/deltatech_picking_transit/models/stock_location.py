from odoo import api, fields, models

TRANSFER_LOCATION_NAME = "CHUYENKHO"


class StockLocation(models.Model):
    _inherit = "stock.location"

    hlv_is_transfer_location = fields.Boolean(
        string="Vị trí chuyển kho",
        copy=False,
        help="Hàng đang chuyển sang kho khác: vẫn tính vào tồn kho nhưng đơn bán không lấy được. "
        "Chỉ dùng làm đích bước 1 / nguồn bước 2 của phiếu chuyển kho nội bộ.",
    )


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    def _hlv_get_transfer_location(self):
        """Vị trí CHUYENKHO của kho, nằm ngang hàng Tồn kho (dưới vị trí view của kho).

        Tự tạo nếu chưa có. Không nhận lại vị trí tên CHUYENKHO có sẵn: đó có thể là khu kệ đang dùng
        (VD TSN/Stock/CHUYENKHO), dời đi sẽ làm đơn bán không lấy được hàng trong đó.
        """
        self.ensure_one()
        # sudo: người quét app mobile không có quyền tạo/sửa vị trí
        Location = self.env["stock.location"].sudo()
        location = Location.search(
            [("hlv_is_transfer_location", "=", True), ("warehouse_id", "=", self.id)], limit=1
        )
        if location:
            return location
        return Location.create({
            "name": TRANSFER_LOCATION_NAME,
            "usage": "internal",
            "location_id": self.view_location_id.id,
            "company_id": self.company_id.id,
            "hlv_is_transfer_location": True,
        })

    @api.model
    def _hlv_ensure_transfer_locations(self):
        """Gọi khi nâng cấp module: tạo CHUYENKHO cho mọi kho."""
        for warehouse in self.search([]):
            warehouse._hlv_get_transfer_location()
        return True
