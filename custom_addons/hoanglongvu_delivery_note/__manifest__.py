{
    "name": "Hoang Long Vu In phiếu",
    "version": "1.0",
    "depends": ["stock","sale"],
    "category": "Warehouse",
    "description": "In Biên Bản Giao Nhận và Logistic Tag trực tiếp từ Delivery Order mới",
    "data": [
        "security/ir.model.access.csv",
        "report/report.xml",
        "views/views.xml",

        "report/report_delivery_note.xml",
        "report/report_logistic_tag.xml",
        'report/report_actions.xml',
        'reports/report_logistic_tag.xml',
        'views/stock_move_views.xml',


    ],
    "installable": True,
    "application": False
}