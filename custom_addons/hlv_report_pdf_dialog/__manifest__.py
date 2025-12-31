
# -*- coding: utf-8 -*-
{
    "name": "Report PDF Preview Dialog",
    "summary": "Open qweb-pdf reports in an in-app dialog with print & download buttons (no new tab)",
    "version": "18.0.1.0.0",
    "author": "Your Company",
    "website": "https://example.com",
    "license": "LGPL-3",
    "category": "Tools",
    "depends": ["web", "point_of_sale"],
    "assets": {
        "web.assets_backend": [
            "hlv_report_pdf_dialog/static/src/report/open_report_handler.js",
            "hlv_report_pdf_dialog/static/src/widgets/print_preview_dialog.js",
            "hlv_report_pdf_dialog/static/src/widgets/print_preview_dialog.xml",
            "hlv_report_pdf_dialog/static/src/widgets/print_preview_dialog.scss",
        ],
        "point_of_sale._assets_pos": [
            "hlv_report_pdf_dialog/static/src/pos/pos_download_patch.js",
        ],
    },
    "installable": True,
    "application": False
}
