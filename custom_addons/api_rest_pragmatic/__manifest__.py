# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Api Rest Pragmatic",
    "summary": """Complete REST API/OpenAPI/Swagger integration for Odoo 18 with advanced ORM methods""",
    
    "description": """
        Api Rest Pragmatic Module
        ======================

        This module provides a complete REST API solution for Odoo 18 with:

        Features
        --------
        * Full REST API implementation with OpenAPI/Swagger documentation
        * Advanced ORM methods (search_or_create, search_read_nested, etc.)
        * Namespace-based API access control
        * Token authentication for secure API access
        * Comprehensive logging system
        * Support for all CRUD operations
        * Custom method calling via API
        * Report generation via API
        * Nested field reading with configurable depth
        * External ID management system

        Technical Features
        -----------------
        * Compatible with Odoo 18.0
        * Follows OWL/QWeb modern conventions
        * PEP8 compliant code
        * Complete test coverage
        * Optimized for performance with proper DB isolation levels
        * Support for parallel query execution

        Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
        Licensed under AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
    """,
    "category": "Technical",
    "version": "18.0.1.0.0",
    "application": False,
    "author": "Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.",
    "maintainers": ["Pragmatic Ingeniería S.A.S."],
    "support": "informacion@pragmaticingenieria.com",
    "website": "https://www.pragmaticingenieria.com/",
    "license": "AGPL-3",
    "depends": ["mail", "web"],
    "external_dependencies": {
        "python": ["bravado_core", "swagger_spec_validator", "jsonschema"],
        "bin": [],
    },
    "data": [
        "security/api_security.xml",
        "security/ir.model.access.csv",
        "views/ir_export_view.xml",
        "views/api_namespace_view.xml",
        "views/api_access_view.xml",
        "views/api_log_view.xml",
        "views/res_users_view.xml",
        "views/ir_model_view.xml",
        "views/menu_view.xml",
    ],
    "demo": [
        "demo/api_demo.xml",
        "demo/api_security_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "api_rest_pragmatic/static/src/css/api_style.css",
        ],
    },
    "images": [
        "static/description/icon.png",
    ],
    "post_load": "post_load",
    "auto_install": False,
    "installable": True,
}
