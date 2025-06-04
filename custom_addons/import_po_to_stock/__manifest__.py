{
    "name": "Enhanced Import PO to Stock",
    "version": "1.1",
    "depends": ["purchase", "stock"],
    "author": "ChatGPT",
    "category": "Warehouse",
    "description": "Import PO file, auto create products if missing, map warehouse by code, and generate incoming shipments.",
    "data": ["views/import_po_wizard_view.xml",
        "views/import_po_menu.xml"],
    "installable": True,
    "license": "LGPL-3",
    "application": False
}