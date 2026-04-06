# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import uuid

from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    namespace_ids = fields.Many2many(
        "api.namespace",
        "api_namespace_users_rel",
        "user_id", 
        "namespace_id",
        string="Allowed API Integrations"
    )
    api_token = fields.Char(
        "API Token",
        default=lambda self: self._get_unique_api_token(),
        required=True,
        copy=False,
        help="Authentication token for access to API (/api).",
    )

    def reset_api_token(self):
        """Reset the API token for selected users."""
        for record in self:
            record.write({"api_token": self._get_unique_api_token()})

    def _get_unique_api_token(self):
        """Generate a unique API token."""
        api_token = str(uuid.uuid4())
        while self.search_count([("api_token", "=", api_token)]):
            api_token = str(uuid.uuid4())
        return api_token

    @api.model
    def reset_all_api_tokens(self):
        """Reset API tokens for all users."""
        self.search([]).reset_api_token()

    def print_api_token(self):
        print("User API Tokens:")