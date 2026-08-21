# -*- coding: utf-8 -*-
from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    hold_requires_approval = fields.Boolean(
        string="Giữ hàng cần duyệt",
        default=True,
        help=(
            "Nếu bật, yêu cầu giữ hàng (từ trang /search_stock) tại kho này phải được "
            "duyệt bởi người có quyền 'Duyệt yêu cầu giữ hàng' trước khi hàng thực sự bị "
            "khóa (reserved). Nếu tắt, yêu cầu giữ hàng được áp dụng ngay khi sale gửi."
        ),
    )
    hold_location_id = fields.Many2one(
        "stock.location",
        string="Vị trí giữ hàng chờ đơn",
        readonly=True,
        copy=False,
        help="Vị trí nội bộ dùng để giữ chỗ hàng cho các yêu cầu giữ hàng (tự tạo khi cần dùng lần đầu).",
    )

    def _get_or_create_hold_location(self):
        self.ensure_one()
        if self.hold_location_id:
            return self.hold_location_id
        location = self.env["stock.location"].sudo().create({
            "name": "Giữ hàng chờ đơn",
            "usage": "internal",
            "location_id": self.view_location_id.id,
            "company_id": self.company_id.id,
        })
        self.hold_location_id = location.id
        return location
