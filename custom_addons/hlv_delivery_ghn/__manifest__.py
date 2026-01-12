{
    "name": "HLV Giao Hàng Nhanh (GHN) Integration",
    "summary": "Calculate shipping fees using GHN API",
    "version": "1.0",
    "category": "Inventory/Delivery",
    "author": "Antigravity",
    "depends": ["stock", "base"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
        "views/stock_picking_views.xml",
        "wizard/ghn_fee_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
