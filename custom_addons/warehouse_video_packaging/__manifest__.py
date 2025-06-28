{
    "name": "Warehouse Video Packaging",
    "version": "1.0",
    "depends": ["stock", "stock_barcode","web"],
    "author": "ChatGPT + Vũ Đức Tập",
    "category": "Warehouse",
    "summary": "Record and upload packaging videos from warehouse operations",
    "data": [
        "security/ir.model.access.csv",
        "views/packaging_video_action_view.xml"
    ],
    "installable": True,
    "application": False,
    "auto_install": False
}
