# -*- coding: utf-8 -*-
"""Mã NCC → sản phẩm bên mình, người bên mình đã xác nhận một lần thì các file sau tự khớp, khỏi hỏi AI lại.

Không ghi vào product.supplierinfo (bảng giá NCC) dù ở đó có sẵn ô "mã NCC": dòng supplierinfo giá 0
sẽ được Odoo / gợi ý NCC của hlv_vendor_quotation coi là một báo giá thật, rồi đưa giá 0 lên đơn mua.
"""

from odoo import api, fields, models


class HlvVendorProductAlias(models.Model):
    _name = "hlv.vendor.product.alias"
    _description = "Mã NCC đã khớp sản phẩm"
    _order = "partner_id, code_key"
    _rec_name = "vendor_code"

    partner_id = fields.Many2one("res.partner", "Nhà cung cấp", required=True, index=True, ondelete="cascade")
    code_key = fields.Char("Khoá mã", required=True, index=True,
                           help="Mã NCC đã chuẩn hoá và bỏ tiền tố riêng của NCC.")
    vendor_code = fields.Char("Mã NCC")
    vendor_name = fields.Char("Tên theo NCC")
    product_id = fields.Many2one("product.product", "Sản phẩm", required=True, ondelete="cascade")
    confirmed_by = fields.Many2one("res.users", "Người xác nhận", default=lambda self: self.env.user)

    _sql_constraints = [
        ("partner_code_uniq", "unique(partner_id, code_key)", "Mã NCC này đã khớp một sản phẩm."),
    ]

    @api.model
    def lookup(self, partner, keys):
        """{khoá mã: sản phẩm} của NCC partner cho các khoá cho trước."""
        aliases = self.search([("partner_id", "=", partner.id), ("code_key", "in", list(keys))])
        return {alias.code_key: alias.product_id for alias in aliases}

    @api.model
    def remember(self, partner, lines):
        """Ghi / cập nhật khoá mã → sản phẩm cho các dòng nhập đã xác nhận có sản phẩm."""
        for line in lines:
            self.link(partner, line.code_key, line.product_id, line.vendor_code, line.vendor_name)

    @api.model
    def link(self, partner, key, product, vendor_code, vendor_name):
        """Ghi / cập nhật một khoá mã NCC → sản phẩm."""
        vals = {"vendor_code": vendor_code, "vendor_name": vendor_name, "product_id": product.id,
                "confirmed_by": self.env.user.id}
        alias = self.search([("partner_id", "=", partner.id), ("code_key", "=", key)], limit=1)
        if not alias:
            return self.create(dict(vals, partner_id=partner.id, code_key=key))
        if alias.product_id != product:
            alias.write(vals)
        return alias
