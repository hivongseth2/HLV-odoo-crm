{
    "name": "Import Stock Transfer HCM",
    "version": "1.0",
    "depends": ["stock"],
    "author": "ChatGPT",
    "category": "Warehouse",
    "license": "LGPL-3",
    "description": "Import stock transfers to/from HCM warehouse from Excel file.",
    "data": [
        "security/ir.model.access.csv",
        "views/import_transfer_menu.xml",
        "wizard/import_transfer_wizard_view.xml"
    ],
    "installable": True,
    "auto_install": False
}