# -*- coding: utf-8 -*-
"""Thành tiền dòng báo giá NCC tính theo SL NCC thật sự bán (allocation_utils.quoted_qty): NCC báo "có X · không có
thêm" thì X, không phải SL hỏi. Dòng đã lưu từ trước vẫn mang thành tiền theo SL hỏi — tính lại (kéo theo tổng báo
giá)."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["hlv.vendor.quote.line"].search([("no_more", "=", True), ("available_qty", ">", 0)])
    lines.modified(["no_more"])
    env.flush_all()
