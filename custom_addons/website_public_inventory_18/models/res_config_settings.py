# -*- coding: utf-8 -*-
from odoo import api, fields, models

class WebsitePublicInventorySettings(models.TransientModel):
    _inherit = "res.config.settings"
    allowed_warehouse_ids = fields.Many2many(
        comodel_name="stock.warehouse",
        string="Public Warehouses",
        help="Warehouses whose stock will be shown on the public inventory page.",
    )
    ...
