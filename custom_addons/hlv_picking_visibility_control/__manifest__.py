# -*- coding: utf-8 -*-
{
    'name': 'HLV - Kiểm soát hiển thị Phiếu bàn giao',
    'version': '18.0.1.0.0',
    'summary': 'Ẩn phiếu bàn giao, BBGN, BBBG - Chỉ hiển thị từ phiếu xuất kho',
    'description': """
    Module này kiểm soát hiển thị các loại phiếu bàn giao:
    - Ẩn các phiếu bàn giao, BBGN, BBBG, phiếu bàn giao từ phiếu nội bộ khỏi menu chính
    - Chỉ cho phép xem/in thông qua phiếu xuất kho chính
    - Thêm trường kiểm soát hiển thị cho stock.picking
    """,
    'author': 'HLV',
    'category': 'Inventory/Inventory',
    'depends': [
        'stock',
        'base',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_picking_views.xml',
        'views/stock_picking_type_views.xml',
    ],
    'assets': {},
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
