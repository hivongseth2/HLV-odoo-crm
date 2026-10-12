# -*- coding: utf-8 -*-
"""Báo giá NCC theo giá đơn mua cho các thay đổi đơn ĐÃ áp trước bản này (vd HG/26/00042: đơn đổi 223.500 → 241.380
mà báo giá vẫn 223.500). Theo thứ tự áp, mỗi dòng đơn lấy giá HIỆN TẠI trên đơn (giá cuối cùng NCC đã sửa) — cùng hàm
với luồng mới (hlv.vendor.quote.line._hlv_follow_order_price)."""
from odoo import SUPERUSER_ID, api

APPLIED_STATES = ("approved", "applied")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    done = set()
    revision_lines = env["hlv.po.revision.line"].search(
        [("revision_id.state", "in", APPLIED_STATES)], order="id")
    for line in revision_lines:
        po_line = line.order_line_id
        if po_line.id in done or "price" not in line._changes() or po_line.state == "cancel":
            continue
        done.add(po_line.id)
        env["hlv.vendor.quote.line"]._hlv_follow_order_price(
            po_line, po_line.price_unit, line.revision_id.purchase_order_id.name)
