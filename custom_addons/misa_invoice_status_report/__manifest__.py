{
    'name': 'MISA Invoice Status Report',
    'version': '1.0',
    'category': 'Inventory',
    'summary': 'Đối soát phiếu xuất kho chưa có hóa đơn MISA',
    'description': """
        App đối soát tình trạng xuất hóa đơn MISA theo từng phiếu xuất kho:
        - Dashboard riêng (OWL): số liệu tổng quan + danh sách phiếu cần hối, không dùng pivot/graph mặc định.
        - Danh sách chi tiết (list view Odoo) để lọc/nhóm/xem từng phiếu.
        - Kiểm tra tự động (cron) và thủ công tình trạng Đề nghị xuất hóa đơn / Hóa đơn trên MISA.
        - Cho phép đánh dấu phiếu là ngoại lệ (chấp nhận chờ xuất hóa đơn).
    """,
    'author': 'Luan',
    'depends': ['base', 'stock', 'sale', 'sale_stock', 'mrp', 'misa_fetch_po_button'],
    'data': [
        'security/misa_invoice_security.xml',
        'security/ir.model.access.csv',
        'wizard/misa_invoice_exception_wizard_views.xml',
        'views/stock_picking_misa_invoice_views.xml',
        'views/misa_invoice_dashboard_views.xml',
        'views/misa_invoice_menus.xml',
        'data/misa_invoice_status_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'misa_invoice_status_report/static/src/scss/misa_invoice_dashboard.scss',
            'misa_invoice_status_report/static/src/xml/misa_invoice_dashboard.xml',
            'misa_invoice_status_report/static/src/js/misa_invoice_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
