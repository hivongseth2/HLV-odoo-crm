{
    'name': 'MISA Invoice Status Report',
    'version': '1.0',
    'category': 'Inventory',
    'summary': 'Đối soát phiếu xuất kho chưa có hóa đơn MISA',
    'description': """
        Báo cáo tình trạng xuất hóa đơn MISA theo từng phiếu xuất kho:
        - Kiểm tra tự động (cron) và thủ công tình trạng Đề nghị xuất hóa đơn / Hóa đơn trên MISA.
        - Dashboard đối soát: chưa có đề nghị / đã đề nghị chờ HĐ / đã xuất HĐ.
        - Cho phép đánh dấu phiếu là ngoại lệ (chấp nhận chờ xuất hóa đơn).
    """,
    'author': 'Luan',
    'depends': ['base', 'stock', 'sale', 'sale_stock', 'misa_fetch_po_button'],
    'data': [
        'security/misa_invoice_security.xml',
        'security/ir.model.access.csv',
        'wizard/misa_invoice_exception_wizard_views.xml',
        'views/stock_picking_misa_invoice_views.xml',
        'data/misa_invoice_status_cron.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
