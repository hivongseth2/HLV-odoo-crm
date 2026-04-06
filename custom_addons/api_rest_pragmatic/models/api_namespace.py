# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import collections
import urllib.parse as urlparse
import uuid

from odoo import api, fields, models

from ..lib import pinguin


class ApiNamespace(models.Model):
    _name = "api.namespace"
    _description = "API Integration"

    active = fields.Boolean("Active", default=True)
    name = fields.Char(
        "Name",
        required=True,
        help="""Integration name, e.g. ebay, amazon, magento, etc.
        The name is used in api endpoint""",
    )
    description = fields.Char("Description")
    log_ids = fields.One2many("api.log", "namespace_id", string="Logs")
    log_count = fields.Integer("Log count", compute="_compute_log_count")
    log_request = fields.Selection(
        [("disabled", "Disabled"), ("info", "Short"), ("debug", "Full")],
        "Log Requests",
        default="disabled",
    )
    log_response = fields.Selection(
        [("disabled", "Disabled"), ("error", "Errors only"), ("debug", "Full")],
        "Log Responses",
        default="error",
    )
    last_log_date = fields.Datetime(compute="_compute_last_used", string="Latest usage")
    
    access_ids = fields.One2many(
        "api.access",
        "namespace_id",
        string="Accesses",
        context={"active_test": False},
    )
    user_ids = fields.Many2many(
        "res.users", 
        "api_namespace_users_rel",
        "namespace_id",
        "user_id",
        string="Allowed Users", 
        default=lambda self: self.env.user
    )
    
    token = fields.Char(
        "Identification token",
        default=lambda self: str(uuid.uuid4()),
        readonly=True,
        required=True,
        copy=False,
        help="Token passed by a query string parameter to access the specification.",
    )
    spec_url = fields.Char("Specification Link", compute="_compute_spec_url")

    _sql_constraints = [
        (
            "name_uniq",
            "unique (name)",
            "A namespace already exists with this name. Namespace's name must be unique!",
        )
    ]

    def name_get(self):
        """Get display name for namespace records."""
        return [
            (
                record.id,
                "/api/v1/%s%s"
                % (
                    record.name,
                    " (%s)" % record.description if record.description else "",
                ),
            )
            for record in self
        ]

    @api.model
    def _fix_name(self, vals):
        """Fix and normalize namespace name."""
        if "name" in vals:
            vals["name"] = urlparse.quote_plus(vals["name"].lower())
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        """Create method that handles both single records and batches."""
        # Handle both single dict and list of dicts
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        
        # Apply _fix_name to each vals dict
        for vals in vals_list:
            self._fix_name(vals)
        
        return super(ApiNamespace, self).create(vals_list)

    def write(self, vals):
        """Write method with name normalization."""
        vals = self._fix_name(vals)
        return super(ApiNamespace, self).write(vals)

    def get_OAS(self):
        """Get OpenAPI Specification for this namespace."""
        current_host = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        parsed_current_host = urlparse.urlparse(current_host)

        report_parameters = [
            {
                "name": "report_external_id",
                "in": "path",
                "description": "Report xml id or report name",
                "required": True,
                "type": "string",
            },
            {
                "name": "docids",
                "in": "path",
                "description": "One identifier or several identifiers separated by commas",
                "required": True,
                "type": "string",
            },
        ]
        
        spec = collections.OrderedDict([
            ("swagger", "2.0"),
            ("info", {"title": self.name, "version": self.write_date}),
            ("host", parsed_current_host.netloc),
            ("basePath", "/api/v1/%s" % self.name),
            ("schemes", [parsed_current_host.scheme]),
            ("consumes", ["multipart/form-data", "application/x-www-form-urlencoded"]),
            ("produces", ["application/json"]),
            ("paths", {
                "/report/pdf/{report_external_id}/{docids}": {
                    "get": {
                        "summary": f"Get PDF report file for {self.name} namespace",
                        "description": f"Returns PDF report file for {self.name} namespace",
                        "operationId": f"getPdfReportFileFor{self.name.capitalize()}Namespace",
                        "produces": ["application/pdf"],
                        "responses": {
                            "200": {
                                "description": f"A PDF report file for {self.name} namespace.",
                                "schema": {"type": "file"},
                            }
                        },
                        "parameters": report_parameters,
                        "tags": ["report"],
                    }
                },
                "/report/html/{report_external_id}/{docids}": {
                    "get": {
                        "summary": f"Get HTML report file for {self.name} namespace",
                        "description": f"Returns HTML report file for {self.name} namespace",
                        "operationId": f"getHtmlReportFileFor{self.name.capitalize()}Namespace",
                        "produces": ["application/pdf"],
                        "responses": {
                            "200": {
                                "description": f"A HTML report file for {self.name} namespace.",
                                "schema": {"type": "file"},
                            }
                        },
                        "parameters": report_parameters,
                        "tags": ["report"],
                    }
                },
            }),
            ("definitions", {
                "ErrorResponse": {
                    "type": "object",
                    "required": ["error", "error_descrip"],
                    "properties": {
                        "error": {"type": "string"},
                        "error_descrip": {"type": "string"},
                    },
                },
            }),
            ("responses", {
                "400": {
                    "description": "Invalid Data",
                    "schema": {"$ref": "#/definitions/ErrorResponse"},
                },
                "401": {
                    "description": "Authentication information is missing or invalid",
                    "schema": {"$ref": "#/definitions/ErrorResponse"},
                },
                "500": {
                    "description": "Server Error",
                    "schema": {"$ref": "#/definitions/ErrorResponse"},
                },
            }),
            ("securityDefinitions", {"basicAuth": {"type": "basic"}}),
            ("security", [{"basicAuth": []}]),
            ("tags", []),
        ])

        for api_access in self.access_ids.filtered("active"):
            OAS_part_for_model = api_access.get_OAS_part()
            spec["tags"].append(OAS_part_for_model["tag"])
            del OAS_part_for_model["tag"]
            pinguin.update(spec, OAS_part_for_model)

        return spec

    @api.depends("name", "token")
    def _compute_spec_url(self):
        """Compute the specification URL for the namespace."""
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        for record in self:
            record.spec_url = "{}/api/v1/{}/swagger.json?token={}&db={}".format(
                base_url,
                record.name,
                record.token,
                self._cr.dbname,
            )

    def reset_token(self):
        """Reset the namespace token."""
        for record in self:
            token = str(uuid.uuid4())
            while self.search([("token", "=", token)]).exists():
                token = str(uuid.uuid4())
            record.write({"token": token})

    def action_show_logs(self):
        """Show logs for this namespace."""
        return {
            "name": "Logs",
            "view_mode": "list,form",
            "res_model": "api.log",
            "type": "ir.actions.act_window",
            "domain": [["namespace_id", "=", self.id]],
        }

    def _compute_last_used(self):
        """Compute the last time this namespace was used."""
        for s in self:
            s.last_log_date = (
                s.env["api.log"]
                .search(
                    [("namespace_id", "=", s.id), ("create_date", "!=", False)],
                    limit=1,
                    order="id desc",
                )
                .create_date
            )

    def _compute_log_count(self):
        """Compute the number of logs for this namespace."""
        self._cr.execute(
            "SELECT COUNT(*) FROM api_log WHERE namespace_id=(%s);", [str(self.id)]
        )
        result = self._cr.dictfetchone()
        self.log_count = result["count"] if result else 0
