{
    "name": "Sale Order Label",
    "version": "1.0",
    "category": "Sales",
    "summary": "Print 40x30mm label for sale orders",
    "depends": ["sale_management", "base", "web"],
    "data": [
        "report/sale_order_label_template.xml",
        "report/sale_order_label_report.xml",
                "views/sale_order_view.xml"

    ],
    "installable": True,
    "application": False,
}
