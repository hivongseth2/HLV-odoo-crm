# -*- coding: utf-8 -*-
"""Tồn kho NCC theo file NCC gửi gần nhất — một dòng cho mỗi mặt hàng × kho của NCC.

File tồn là ảnh chụp toàn bộ: áp file mới thì thay hết tồn cũ của NCC đó. Dòng chưa khớp sản phẩm bên
mình vẫn giữ (theo mã NCC) — tra được, và khớp sau thì lần nhập tới tự gắn.
"""

from odoo import api, fields, models


class HlvVendorStock(models.Model):
    _name = "hlv.vendor.stock"
    _description = "Tồn kho NCC"
    _order = "partner_id, vendor_code, warehouse"

    partner_id = fields.Many2one("res.partner", "Nhà cung cấp", required=True, index=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", "Sản phẩm", index=True, ondelete="set null")
    # Khoá mã NCC (bỏ tiền tố; không có mã thì tên đã chuẩn hoá) — như hlv.vendor.price, để tra khi khớp sau.
    match_key = fields.Char("Khoá", index=True)
    vendor_code = fields.Char("Mã NCC")
    vendor_name = fields.Char("Tên theo NCC")
    uom_name = fields.Char("ĐVT NCC")
    warehouse = fields.Char("Kho NCC")
    qty = fields.Float("Tồn", digits="Product Unit of Measure")
    import_id = fields.Many2one("hlv.vendor.import", "Lần nhập", ondelete="set null")
    date = fields.Datetime("Cập nhật")

    @api.model
    def replace_for(self, partner, rows):
        """Thay toàn bộ tồn của NCC partner bằng rows (list dict giá trị, chưa có partner_id)."""
        self.search([("partner_id", "=", partner.id)]).unlink()
        return self.create([dict(row, partner_id=partner.id) for row in rows])
