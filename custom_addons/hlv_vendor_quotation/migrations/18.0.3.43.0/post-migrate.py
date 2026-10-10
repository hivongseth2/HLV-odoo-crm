# -*- coding: utf-8 -*-
"""YCMH lên từ trang hỏi giá trước bản này chỉ có cột thu mua (actual_*) — điền bù bộ cột "sale đề
xuất" (NCC / giá / thuế) từ giá sale đã chọn, chỉ dòng còn trống để không đè số ai đã sửa tay."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["hlv.vendor.inquiry.line"].search([
        ("request_line_id", "!=", False),
        ("chosen_line_id", "!=", False),
        ("request_line_id.request_id.hlv_from_quote_page", "=", True),
        ("request_line_id.sale_proposed_supplier_id", "=", False),
        ("request_line_id.misa_price_before_tax", "=", 0),
    ])
    for line in lines:
        line.request_line_id.write(line.chosen_line_id._request_line_proposal_vals())
