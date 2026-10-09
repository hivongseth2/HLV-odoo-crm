# -*- coding: utf-8 -*-
"""YCMH bị từ chối trước bản này vẫn giữ lựa chọn NCC trên phiếu hỏi giá — nhả ra như khi từ chối mới."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["purchase.request"].search([("state", "=", "rejected")])._hlv_release_rejected_choices()
