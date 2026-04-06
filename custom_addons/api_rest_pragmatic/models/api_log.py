# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ApiLog(models.Model):
    _name = "api.log"
    _description = "API Request Log"

    namespace_id = fields.Many2one("api.namespace", "Namespace", required=True)
    request = fields.Text("Request", help="Request summary")
    request_data = fields.Text("Request Data")
    response_data = fields.Text("Response Data")
    create_date = fields.Datetime("Created", readonly=True)
    
    def name_get(self):
        """Get display name for log records."""
        return [
            (record.id, f"{record.namespace_id.name} - {record.create_date or 'No date'}")
            for record in self
        ]
