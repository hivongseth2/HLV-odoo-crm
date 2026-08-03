# -*- coding: utf-8 -*-
{
    'name': 'Stock Picking Type Domain Filter',
    'version': '18.0.1.0.1',
    'category': 'Inventory/Inventory',
    'summary': 'Giới hạn loại hoạt động picking theo ngữ cảnh',
    'description': """
        Module này giới hạn các loại hoạt động (picking type) hiển thị trong stock.picking
        dựa trên nguồn gốc của picking:
        - Bán hàng (Sale Order): Lấy hàng, Gói, Lệnh giao hàng
        - Mua hàng (Purchase Order): Phiếu nhập kho
        - Phiếu trả hàng: Lọc theo chiều hoạt động đã đảo ngược
        - Chuyển hàng nội bộ: Lệnh chuyển hàng nội bộ
        - Các trường hợp khác: Hiển thị tất cả
    """,
    'author': 'HLV',
    'website': 'https://www.hoanglongvu.com',
    'depends': ['stock', 'sale_stock', 'purchase_stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
