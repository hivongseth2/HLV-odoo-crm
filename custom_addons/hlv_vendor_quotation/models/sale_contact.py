# -*- coding: utf-8 -*-
"""Danh bạ sale: mã sale MISA → tên, điện thoại, email.

Trang /hoi-gia-ncc và trang NCC hiện tên sale thay cho mã, và NCC biết ai hỏi giá, gọi số
nào. Mã sale chưa có trong danh bạ thì vẫn hiện mã như cũ.
"""

from odoo import api, fields, models, tools

from .vendor_quote_utils import requester_text


class VendorSaleContact(models.Model):
    _name = "hlv.vendor.sale.contact"
    _description = "Sale hỏi giá NCC"
    _order = "name"
    _rec_name = "name"

    sale_code = fields.Char(string="Mã sale MISA", required=True, index=True)
    name = fields.Char(string="Tên hiển thị", required=True, help="Tên hiện cho NCC và trên trang hỏi giá, VD Trâm Bến Cam.")
    phone = fields.Char(string="Điện thoại", help="Hiện cho NCC để liên hệ người hỏi giá.")
    email = fields.Char(string="Email", help="Email gửi NCC đặt trả lời về địa chỉ này.")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("sale_code_uniq", "unique(sale_code)", "Mã sale này đã có trong danh bạ."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals["sale_code"] = (vals.get("sale_code") or "").strip()
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        if "sale_code" in vals:
            vals["sale_code"] = (vals["sale_code"] or "").strip()
        result = super().write(vals)
        self.env.registry.clear_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache()
        return result

    @api.model
    @tools.ormcache()
    def _contact_map(self):
        """{MÃ SALE viết hoa: {"name", "phone", "email"}} — đọc nhiều lần mỗi trang nên cache;
        sửa danh bạ là xoá cache (create / write / unlink ở trên)."""
        contacts = self.sudo().search([])
        return {
            c.sale_code.upper(): {"name": c.name or "", "phone": c.phone or "", "email": c.email or ""}
            for c in contacts
        }

    @api.model
    def _for_code(self, code):
        """Thông tin sale của một mã (không phân biệt hoa thường), không có → None."""
        return self._contact_map().get((code or "").strip().upper())

    @api.model
    def _name_map(self):
        """{mã viết hoa: tên} cho JS trang sale tự đổi mã ra tên."""
        return {code: info["name"] for code, info in self._contact_map().items()}

    @api.model
    def _requester(self, code):
        """"Tên – SĐT" người hỏi giá để NCC biết ai hỏi; mã chưa có trong danh bạ → mã; rỗng → ""."""
        info = self._for_code(code)
        if not info:
            return (code or "").strip()
        return requester_text(info["name"], info["phone"])
