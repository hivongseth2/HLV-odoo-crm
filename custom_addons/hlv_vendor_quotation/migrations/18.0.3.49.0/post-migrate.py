# -*- coding: utf-8 -*-
"""Link NCC rút gọn: cấp mã ngắn cho các link đã có (link mới tạo tự có). Link dài cũ vẫn mở được."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Access = env["hlv.vendor.quote.access"].with_context(active_test=False)
    for access in Access.search([("short_code", "=", False)]):
        access.short_code = Access._new_short_code()
