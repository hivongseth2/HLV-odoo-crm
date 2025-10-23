{
    "name": "HLV Tracking AfterShip",
    "version": "18.0.1.0.1",
    "summary": "Track J&T Express VN via AfterShip (slug: jtexpress-vn)",
    "author": "Hoang Long Vu + ChatGPT",
    "license": "LGPL-3",
    "depends": ["stock","website"],
    "data": [
        "views/stock_picking_buttons.xml",
        "data/ir_cron.xml",
        "views/website_tracking.xml" 
    ],
    "installable": True,
    "application": False
}