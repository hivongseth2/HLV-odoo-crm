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
        existing = {alias.code_key: alias for alias in self.search([
            ("partner_id", "=", partner.id), ("code_key", "in", lines.mapped("code_key"))])}
        for line in lines:
            vals = {"vendor_code": line.vendor_code, "vendor_name": line.vendor_name,
                    "product_id": line.product_id.id, "confirmed_by": self.env.user.id}
            alias = existing.get(line.code_key)
            if alias:
                if alias.product_id != line.product_id:
                    alias.write(vals)
            else:
                existing[line.code_key] = self.create(dict(vals, partner_id=partner.id, code_key=line.code_key))
