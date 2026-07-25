# -*- coding: utf-8 -*-
{
    'name': 'Stock Quantity Validation',
    'version': '1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Chặn xác nhận picking khi quantity lớn hơn product_uom_qty',
    'description': """
        Module này ngăn chặn việc xác nhận phiếu kho (picking) khi số lượng thực tế
        (qty_done) lớn hơn số lượng đã đặt (product_uom_qty) trên stock.move.

        Tính năng:
        - Kiểm tra tất cả move lines trong picking
        - Hiển thị thông báo lỗi chi tiết với danh sách sản phẩm vi phạm
        - Áp dụng cho tất cả loại picking (Pick, Pack, Delivery/Out, Receipt, etc.)
    """,
    'author': 'HLV',
    'website': 'https://github.com/hivongseth2/HLV-odoo-crm',
    'depends': ['stock'],
    'data': [],
    # 'installable': True,  # TẠM TẮT ĐỂ BUILD - module guard gây lỗi test Odoo core
    'installable': False,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
