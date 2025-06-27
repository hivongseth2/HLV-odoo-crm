{
    "name": "Warehouse Video Packaging",
    "version": "1.0",
    "depends": ["stock", "stock_barcode"],
    "author": "ChatGPT + Vũ Đức Tập",
    "category": "Warehouse",
    "summary": "Record and upload packaging videos from warehouse operations",
    "data": [
        "security/ir.model.access.csv",
        "views/packaging_video_view.xml",
        "views/packaging_video_action_view.xml"
    ],
    "installable": true,
    "application": false,
    "auto_install": false
}
