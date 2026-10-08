# -*- coding: utf-8 -*-
"""Thêm "giá hiệu lực đến": báo giá đã gửi giá trước bản này lấy ngày gửi + 7 ngày."""

from datetime import datetime

from odoo import SUPERUSER_ID, api

from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import default_price_valid_until, local_date_text


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    quotes = env["hlv.vendor.quote"].search([
        ("state", "in", ("quoted", "done")), ("submit_date", "!=", False), ("price_valid_until", "=", False),
    ])
    for quote in quotes:
        # Ngày gửi theo giờ VN (submit_date lưu UTC).
        submit_day = datetime.strptime(local_date_text(quote.submit_date, "%Y-%m-%d"), "%Y-%m-%d").date()
        quote.price_valid_until = default_price_valid_until(submit_day)
