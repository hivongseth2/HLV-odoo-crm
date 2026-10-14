# -*- coding: utf-8 -*-
"""Bảng giá NCC theo file NCC gửi — mỗi mã NCC một chuỗi giá theo ngày hiệu lực.

Khác bảng tồn (ảnh chụp toàn bộ, thay hết): NCC hay gửi "điều chỉnh giá MỘT PHẦN sản phẩm, áp dụng từ ngày X".
Áp file giá chỉ đụng các mã có trong file: giá mới hiệu lực từ ngày X, giá cũ của mã đó dừng ở ngày X (giữ để tra);
mã không có trong file giữ nguyên giá đang có. Ngày X có thể ở tương lai — trước ngày đó vẫn dùng giá cũ.
"""

from odoo import api, fields, models
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_line import VAT_SELECTION


class HlvVendorPrice(models.Model):
    _name = "hlv.vendor.price"
    _description = "Bảng giá NCC"
    _order = "partner_id, vendor_code, date_from desc"

    partner_id = fields.Many2one("res.partner", "Nhà cung cấp", required=True, index=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", "Sản phẩm", index=True, ondelete="set null")
    # Khoá để nối các lần nhập: khoá mã NCC (bỏ tiền tố), không có mã thì tên đã chuẩn hoá.
    match_key = fields.Char("Khoá", required=True, index=True)
    vendor_code = fields.Char("Mã NCC")
    vendor_name = fields.Char("Tên theo NCC")
    uom_name = fields.Char("ĐVT NCC")
    price = fields.Float("Giá chưa VAT", digits=(16, 2), help="Giá NCC ghi trên file (giá niêm yết, chưa trừ chiết khấu).")
    price_incl = fields.Float("Giá sau VAT", digits=(16, 2))
    vat = fields.Selection(VAT_SELECTION, "VAT", help="Trống: file không ghi VAT.")
    date_from = fields.Date("Áp dụng từ", required=True, index=True)
    date_to = fields.Date("Đến trước ngày", index=True, help="Trống: còn hiệu lực tới khi có giá mới.")
    import_id = fields.Many2one("hlv.vendor.import", "Lần nhập", ondelete="set null")

    @api.model
    def apply_for(self, partner, rows, date_from):
        """Ghi giá các mã trong rows (dict giá trị, có match_key, chưa có partner_id) từ ngày date_from.

        Mỗi mã: giá cũ cùng ngày bị thay; giá cũ đang hiệu lực qua ngày đó dừng lại ở date_from; đã có giá cho ngày
        sau đó (nhập trước một thông báo xa hơn) thì giá mới dừng ở ngày đó. Mã khớp sản phẩm thì gắn sản phẩm cho
        cả các giá cũ cùng mã chưa gắn. Trả các dòng giá vừa tạo."""
        keys = {row["match_key"] for row in rows}
        # Bảng giá mới có thể có mã AI chưa thấy lần trước: sản phẩm "không có mã nào khớp" được dò lại.
        self.env["hlv.vendor.code.suggestion"].search([("partner_id", "=", partner.id), ("state", "=", "none")]).unlink()
        existing = self.search([("partner_id", "=", partner.id), ("match_key", "in", list(keys))])
        existing.filtered(lambda price: price.date_from == date_from).unlink()
        existing = existing.exists()
        later_start = {}
        for price in existing:
            if price.date_from > date_from:
                later_start[price.match_key] = min(later_start.get(price.match_key, price.date_from), price.date_from)
        existing.filtered(lambda price: price.date_from < date_from and (not price.date_to or price.date_to > date_from)
                          ).write({"date_to": date_from})
        for row in rows:
            if row.get("product_id"):
                existing.filtered(lambda price: price.match_key == row["match_key"] and not price.product_id).write(
                    {"product_id": row["product_id"]})
        return self.create([dict(row, partner_id=partner.id, date_from=date_from,
                                 date_to=later_start.get(row["match_key"], False)) for row in rows])

    @api.model
    def current_price(self, partner, product, on_date):
        """Giá NCC (công ty của partner) đang hiệu lực ngày on_date cho product — bản ghi, hoặc rỗng."""
        if not partner or not product:
            return self.browse()
        return self.search([
            ("partner_id", "=", partner.commercial_partner_id.id), ("product_id", "=", product.id),
            ("date_from", "<=", on_date), "|", ("date_to", "=", False), ("date_to", ">", on_date),
        ], order="date_from desc, id desc", limit=1)
