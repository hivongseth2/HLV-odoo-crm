{
    "name": "Custom Barcode Pack Scan",
    "version": "1.0",
    "depends": ["stock", "stock_barcode", "hlv_pack_sequence"],
    "author": "Anh Yêu",
    "category": "Warehouse",
    "summary": "Scan từng sản phẩm trong phiếu Pack bằng barcode + Partial Pack Management",
    "data": [
        "views/pack_scan_template.xml",
        "views/menu.xml",
        "views/scan_ui_template.xml",
        "views/res_config_settings_view.xml",
        "views/access_denied_template.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "assets": {
        "web.assets_frontend": [
            "custom_barcode_scan_redirect/static/src/js/toast.js",
            "custom_barcode_scan_redirect/static/src/js/ui_utils.js",
            "custom_barcode_scan_redirect/static/src/js/server_sync.js",
            "custom_barcode_scan_redirect/static/src/js/recording.js",
            "custom_barcode_scan_redirect/static/src/js/side_panel.js",
            "custom_barcode_scan_redirect/static/src/js/package_edit.js",
            "custom_barcode_scan_redirect/static/src/js/transfer_modal.js",
            "custom_barcode_scan_redirect/static/src/js/scan_pack.js",
            "custom_barcode_scan_redirect/static/src/js/scan_ui.js",
        ]
    },
    # 'external_dependencies': {'python': ['pydrive2']},
    'external_dependencies': {'python': ['pydrive2','oauth2client']},
}