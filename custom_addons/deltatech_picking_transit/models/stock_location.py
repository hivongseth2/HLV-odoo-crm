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

    def _hlv_transfer_out_type(self):
        """Loại phiếu bước 1 (Tồn kho → CHUYENKHO) của kho: loại đánh dấu "Xuất kho" chuyển kho 2 bước (CKD);
        kho chưa có thì Lệnh chuyển nội bộ (INT) như trước khi tách."""
        self.ensure_one()
        return self.env["stock.picking.type"].search([
            ("warehouse_id", "=", self.id), ("code", "=", "internal"), ("two_step_transfer_use", "=", "delivery"),
        ], limit=1) or self.int_type_id

    def _hlv_transfer_in_type(self):
        """Loại phiếu bước 2 (CHUYENKHO kho gửi → kho này): loại đánh dấu "Nhập kho" (CKN); kho chưa có thì loại
        nội bộ đi vào vị trí tồn, ưu tiên INT. Loại trừ PICK/PACK, loại bước 1 (đích CHUYENKHO) và loại đi ra vị
        trí ảo (Xuất kho sử dụng / thất thoát) — rơi vào đó thì hàng chuyển kho nhập sai chỗ hoặc mất khỏi tồn."""
        self.ensure_one()
        types = self.env["stock.picking.type"].search([("warehouse_id", "=", self.id), ("code", "=", "internal")])
        reception = types.filtered(lambda t: t.two_step_transfer_use == "reception")[:1]
        if reception:
            return reception
        types = (types - self.pick_type_id - self.pack_type_id).filtered(lambda t: (
            t.two_step_transfer_use != "delivery"
            and t.default_location_dest_id.usage == "internal"
            and not t.default_location_dest_id.hlv_is_transfer_location
        ))
        return self.int_type_id if self.int_type_id in types else types[:1]

    @api.model
    def _hlv_ensure_transfer_locations(self):
        """Gọi khi nâng cấp module: tạo CHUYENKHO cho mọi kho."""
        for warehouse in self.search([]):
            warehouse._hlv_get_transfer_location()
        return True
