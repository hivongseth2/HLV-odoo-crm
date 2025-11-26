{
    'name': "Stock Dashboard Grouped by Warehouse",
    'summary': """
        Gộp các thẻ hoạt động (Picking Type) vào trong thẻ Warehouse trên Dashboard.
    """,
    'description': """
        Module này thay đổi giao diện Inventory Dashboard:
        - Thay vì hiển thị từng Picking Type (Nhập, Xuất, Nội bộ) rời rạc.
        - Nó sẽ hiển thị danh sách các Kho (Warehouse).
        - Bên trong mỗi Kho sẽ có danh sách các hoạt động con kèm số lượng cần xử lý.
        - Hỗ trợ Odoo 18, không hardcode, tự động cập nhật theo cấu hình.
    """,
    'author': "Your Name / Company",
    'website': "https://www.yourcompany.com",
    'category': 'Inventory/Inventory',
    'version': '18.0.1.0.0',

    # Module này phụ thuộc vào module 'stock' (Kho vận)
    'depends': ['base', 'stock'],

    # Danh sách các file XML cần load (quan trọng)
    'data': [
        'views/stock_warehouse_views.xml',
    ],

    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}