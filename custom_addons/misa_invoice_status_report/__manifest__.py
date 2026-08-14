{
    'name': 'MISA Invoice Status Report',
    'version': '1.6',
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
    # amis_callback: dùng model amis.misa.inventory.cache (đã đồng bộ sẵn quy đổi đơn vị
    # tính từ MISA) để đối chiếu số lượng từng dòng hàng không bị báo lệch sai khi Odoo và
    # MISA ghi nhận cùng 1 mặt hàng ở 2 đơn vị tính khác nhau (VD 1000 Cái = 5 Bịch).
    'depends': ['base', 'stock', 'sale', 'sale_stock', 'mrp', 'misa_fetch_po_button', 'amis_callback', 'website'],
    'data': [
        'security/misa_invoice_security.xml',
        'security/ir.model.access.csv',
        'wizard/misa_invoice_exception_wizard_views.xml',
        'wizard/misa_invoice_manual_link_wizard_views.xml',
        'views/stock_picking_misa_invoice_views.xml',
        'views/misa_invoice_dashboard_views.xml',
        'views/misa_invoice_menus.xml',
        'views/misa_invoice_customs_line_views.xml',
        'views/res_users_misa_invoice_views.xml',
        'views/misa_sale_status_templates.xml',
        'data/misa_invoice_status_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'misa_invoice_status_report/static/src/scss/misa_invoice_dashboard.scss',
            'misa_invoice_status_report/static/src/xml/misa_invoice_dashboard.xml',
            'misa_invoice_status_report/static/src/js/misa_invoice_dashboard.js',
            'misa_invoice_status_report/static/src/xml/misa_order_list_page.xml',
            'misa_invoice_status_report/static/src/js/misa_order_list_page.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    # Backfill misa_invoice_net_actual_amount cho phiếu cũ khi CÀI MỚI module (trường hợp
    # nâng cấp module đã cài sẵn thì dùng migrations/1.2/post-migrate.py thay vì hook này, vì
    # post_init_hook không chạy khi upgrade module đã cài).
    'post_init_hook': 'post_init_hook',
}
