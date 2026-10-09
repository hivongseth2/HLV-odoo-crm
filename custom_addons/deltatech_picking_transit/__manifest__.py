{
    "name": "Stock Auto Transfer",
    "version": "18.0.0.1.2",
    "author": "Terrabit, Voicu Stefan",
    "website": "https://www.terrabit.ro",
    "category": "Warehouse",
    "summary": "Chuyển kho 2 bước qua vị trí CHUYENKHO của kho nguồn",
    "depends": ["stock"],
    "license": "LGPL-3",
    "data": [
        "security/ir.model.access.csv",
        "data/transfer_location_data.xml",
        "views/stock_picking_views.xml",
        "wizard/stock_picking_transfer_wizard_views.xml",
        "views/stock_picking_type_view.xml",
    ],
    "development_status": "Beta",
    "maintainers": ["VoicuStefan2001"],
}
