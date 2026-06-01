# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_invoice_guard_api_token = fields.Char(
        string="Invoice Guard API Token",
        config_parameter="hlv_invoice_guard.api_token",
        groups="base.group_system",
    )
