# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    # Lần cuối người dùng mở chuông thông báo trên /hoi-gia-ncc: báo giá NCC gửi sau mốc này là
    # "mới" (services/sale_feed.py). Ghi bằng sudo — người dùng không tự ghi được trường trên res.users.
    hlv_vq_bell_seen_at = fields.Datetime(string="Đã xem thông báo báo giá NCC lúc", readonly=True, copy=False)
