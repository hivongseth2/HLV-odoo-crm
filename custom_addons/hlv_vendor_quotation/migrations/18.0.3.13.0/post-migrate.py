# -*- coding: utf-8 -*-
"""Bản có nhóm quyền riêng: gán nhóm cho người đang dùng trang (cài mới thì hooks.py làm)."""

from odoo import SUPERUSER_ID, api

from odoo.addons.hlv_vendor_quotation.services.access_setup import grant_default_groups


def migrate(cr, version):
    grant_default_groups(api.Environment(cr, SUPERUSER_ID, {}))
