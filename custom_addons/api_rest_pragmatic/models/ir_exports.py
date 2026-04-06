# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class IrExports(models.Model):
    _inherit = "ir.exports"

    api_access_read_one_ids = fields.One2many(
        "api.access",
        "read_one_id", 
        string="API Access Read One"
    )
    api_access_read_many_ids = fields.One2many(
        "api.access",
        "read_many_id",
        string="API Access Read Many"
    )
