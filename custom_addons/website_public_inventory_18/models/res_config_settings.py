
# -*- coding: utf-8 -*-
from odoo import api, fields, models

class WebsitePublicInventorySettings(models.TransientModel):
    _inherit = "res.config.settings"

    allowed_warehouse_ids = fields.Many2many(
        comodel_name="stock.warehouse",
        string="Public Warehouses",
        help="Warehouses whose stock will be shown on the public inventory page.",
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        param = self.env["ir.config_parameter"].sudo()
        raw = param.get_param("website_public_inventory_18.allowed_warehouse_ids", default="")
        ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
        res.update(allowed_warehouse_ids=[(6, 0, ids)])
        return res

    def set_values(self):
        super().set_values()
        param = self.env["ir.config_parameter"].sudo()
        ids = ",".join(str(x) for x in self.allowed_warehouse_ids.ids)
        param.set_param("website_public_inventory_18.allowed_warehouse_ids", ids)
