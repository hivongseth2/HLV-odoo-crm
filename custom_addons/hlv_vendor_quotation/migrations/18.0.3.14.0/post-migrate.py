# -*- coding: utf-8 -*-
"""Tên xuất hóa đơn trên dòng đơn mua chuyển từ field tính sang field lưu: điền cho đơn mua đã có."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["purchase.order.line"]._hlv_backfill_invoice_names()
