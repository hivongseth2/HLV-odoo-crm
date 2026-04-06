# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class IrModel(models.Model):
    _inherit = "ir.model"

    api_access_ids = fields.One2many(
        "api.access",
        "model_id",
        string="API Access",
        context={"active_test": False}
    )
    api_access_count = fields.Integer(
        "API Access Count", 
        compute="_compute_api_access_count"
    )

    @api.depends("api_access_ids")
    def _compute_api_access_count(self):
        """Compute the number of API access configurations for this model."""
        for record in self:
            record.api_access_count = len(record.api_access_ids)
