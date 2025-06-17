{
    "name": "MISA Sale Orders Import via API",
    "version": "1.0",
    "category": "Sales",
    "summary": "Import đơn bán từ MISA qua API",
    "author": "ChatGPT",
    "depends": ["sale", "stock", "crm"],
    "data": [
        "views/sale_api_import_wizard_view.xml",
        "security/ir.model.access.csv"
    ],
    "installable": True,
    "auto_install": False,
}
