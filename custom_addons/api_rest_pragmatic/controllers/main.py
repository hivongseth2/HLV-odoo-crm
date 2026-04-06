# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""OpenAPI Specification Controller."""

import json
import logging

import werkzeug
from odoo import http
from odoo.tools import date_utils
from odoo.addons.web.controllers.utils import ensure_db

_logger = logging.getLogger(__name__)


class OAS(http.Controller):
    """OpenAPI Specification controller."""
    
    @http.route(
        "/api/v1/<namespace_name>/swagger.json",
        type="http",
        auth="none",
        csrf=False,
    )
    def OAS_json_spec_download(self, namespace_name, **kwargs):
        """Download OpenAPI specification for a namespace."""
        ensure_db()
        namespace = (
            http.request.env["api.namespace"]
            .sudo()
            .search([("name", "=", namespace_name)])
        )
        if not namespace:
            raise werkzeug.exceptions.NotFound()
        if namespace.token != kwargs.get("token"):
            raise werkzeug.exceptions.Forbidden()
        
        response_params = {"headers": [("Content-Type", "application/json")]}
        if "download" in kwargs:
            response_params = {
                "headers": [
                    ("Content-Type", "application/octet-stream; charset=binary"),
                    ("Content-Disposition", http.content_disposition("swagger.json")),
                ],
                "direct_passthrough": True,
            }
        
        return werkzeug.wrappers.Response(
            json.dumps(namespace.get_OAS(), default=str),
            status=200,
            **response_params
        )
