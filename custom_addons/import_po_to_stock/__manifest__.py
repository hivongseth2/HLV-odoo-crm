{
    "name": "Import PO to Stock",
    "version": "1.0",
    "depends": ["stock", "purchase"],
    "author": "ChatGPT",
    "category": "Warehouse",
    "license": "LGPL-3",
    "description": "Import PO Excel file, auto-create products, map warehouses, and generate incoming shipments.",
    "data": [
        "security/ir.model.access.csv",
        "views/import_po_menu.xml",
        "wizard/import_po_wizard_view.xml"
    ],
    "installable": True,
    "auto_install": False
}
