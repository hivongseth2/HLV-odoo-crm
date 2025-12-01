{
    "name": "Sale Order Label",
    "version": "1.0",
    "category": "Sales",
    "summary": "Print 40x30mm label for sale orders and stock pickings",
    "depends": ["sale_management", "stock", "base", "web"],
    "data": [
        "report/sale_order_label_template.xml",
        "report/sale_order_label_report.xml",
        "report/stock_picking_label_template.xml",
        "report/stock_picking_label_report.xml",
        "views/sale_order_view.xml",
        "views/stock_picking_view.xml",
    ],
    "installable": True,
    "application": False,
}
