{
    'name': 'HLV PO Origin Reservation',
    'version': '18.0.1.0.0',
    'summary': 'Tự động giữ hàng cho đơn bán hàng khi nhập kho từ PO',
    'description': """
        Khi nhập kho từ Purchase Order, module sẽ:
        - Đọc trường "Chứng từ gốc" (origin) trên PO
        - Tìm Sale Order có tên trùng khớp
        - Tự động giữ hàng (reserve) cho phiếu giao hàng của SO đó
        - Nếu không tìm thấy SO, giữ hành vi mặc định của Odoo 18
    """,
    'category': 'Inventory/Inventory',
    'author': 'HLV',
    'depends': ['purchase_stock', 'sale_stock'],
    'data': [],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
