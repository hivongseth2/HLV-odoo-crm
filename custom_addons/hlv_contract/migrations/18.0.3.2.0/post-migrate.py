# -*- coding: utf-8 -*-
"""Bản 3.2: mỗi hợp đồng giữ bản chụp nội dung riêng. Hợp đồng lập trước bản này chưa có bản
chụp: chụp theo mẫu hiện tại (là nội dung chúng đang hiện), từ nay sửa mẫu không đổi chúng nữa."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    contracts = env['hlv.contract'].with_context(active_test=False).search([])
    contracts.filtered(lambda c: not c._has_snapshot())._snapshot_template()
