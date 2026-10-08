# -*- coding: utf-8 -*-
from odoo import fields, models

from .vendor_quote_access import REQUIRE_PASSWORD_PARAM


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_vq_require_password = fields.Boolean(
        string="NCC nhập mật khẩu khi mở link báo giá",
        config_parameter=REQUIRE_PASSWORD_PARAM,
    )
