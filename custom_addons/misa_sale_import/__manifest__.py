{
    "name": "MISA Sale Order Import",
    "version": "1.3",
    "summary": "Import MISA-approved Sale Orders into Odoo (auto confirm)",
    "description": "Imports approved sale orders from MISA, auto-creates customers/products, confirms orders, assigns sales teams.",
    "category": "Sales",
    "author": "Custom",
    "depends": ["sale_management", "stock", "base", "crm"],
    "data": [
        "security/ir_model_access.xml",
        "views/sale_import_wizard_views.xml",
        "views/sale_order_views.xml"
    ],
    "installable": True,
    "application": True,
    "auto_install": False
}