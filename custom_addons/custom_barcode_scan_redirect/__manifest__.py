{
    "name": "Custom Barcode Scan Redirect",
    "version": "0.0.1",
    "depends": ["stock", "stock_barcode"],
    "author": "ChatGPT Dev",
    "category": "Warehouse",
    "summary": "Redirect barcode scan to next picking if current is done, then load Odoo's native barcode view.",
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "data": ["views/scan_ui_template.xml"],
}



