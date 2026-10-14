# -*- coding: utf-8 -*-
"""Sale / MISA tạo mã hoặc đổi mã sản phẩm → gắn luôn vào bảng giá / tồn kho NCC đã nhập nếu trùng mã chắc chắn
(vendor_code_match.py). Bảng giá NCC thường nhập trước, sản phẩm chỉ được tạo khi có khách hỏi."""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        products._hlv_link_vendor_rows()
        return products

    def write(self, vals):
        result = super().write(vals)
        if "default_code" in vals:
            self._hlv_link_vendor_rows()
        return result

    def _hlv_link_vendor_rows(self):
        # Việc phụ: lỗi ở đây không được chặn tạo / sửa sản phẩm (đồng bộ MISA tạo hàng loạt). Người tạo mã thường
        # không có quyền thu mua trên bảng giá NCC — chạy sudo, chỉ gắn khi trùng mã chắc chắn.
        try:
            with self.env.cr.savepoint():
                self.env["hlv.vendor.code.match"].sudo().link_products(self.sudo())
        except Exception:  # noqa: BLE001
            _logger.exception("VENDOR_CODE_MATCH lỗi khi gắn sản phẩm %s vào bảng giá NCC", self.ids)
