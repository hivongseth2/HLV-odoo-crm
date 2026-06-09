{
    "name": "HLV Mobile Barcode Scanner",
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "summary": "Mobile-optimized barcode scanning application for warehouse operations",
    "description": """
Mobile Barcode Scanner
======================
- Smart Routing Scan (Auto detect Picking/Product/Location/Package)
- Mobile-optimized UI with OWL
- Support Picking, Internal Transfer, Location Moves, Put in Pack
    """,
    "author": "HLV",
    "depends": [
        "base", 
        "stock", 
        "sale_stock",
        "stock_barcode",
        "web",
        "hlv_sale_delivery_planning",
        # === OPTION B: DEPENDS ON WAREHOUSE PERMISSION ===
        # "hlv_warehouse_permission",
        # =================================================
    ],
    "data": [
        # === OPTION A: SELF-CONTAINED BARCODE PERMISSIONS ===
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/default_odoo_barcode_access.xml",
        "views/barcode_permission_views.xml",
        # ====================================================
        "views/res_config_settings_views.xml",
        "views/barcode_menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hlv_mobile_barcode/static/src/css/barcode_mobile.css",
            "hlv_mobile_barcode/static/src/components/**/*.js",
            "hlv_mobile_barcode/static/src/components/**/*.xml",
        ],
    },
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
