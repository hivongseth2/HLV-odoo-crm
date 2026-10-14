# -*- coding: utf-8 -*-
"""Trang sale (/hoi-gia-ncc): dòng NCC có gợi ý khớp mã chờ xác nhận thì hiện link tới trang xác nhận."""

from odoo import models

from .vendor_code_suggestion import SUGGESTION_ROUTE


class VendorQuote(models.Model):
    _inherit = "hlv.vendor.quote"

    def _hlv_sale_page_links(self):
        links = super()._hlv_sale_page_links()
        count = self.env["hlv.vendor.code.suggestion"].sudo().search_count(
            [("quote_id", "=", self.id), ("state", "=", "pending")])
        if count:
            links.append({"label": f"Bảng giá NCC: {count} mã chờ xác nhận", "url": f"{SUGGESTION_ROUTE}/{self.id}",
                          "highlight": True})
        return links
