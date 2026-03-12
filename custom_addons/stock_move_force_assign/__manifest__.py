{
    'name': 'Stock Move Force Assign',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Cải thiện logic assign stock, xử lý trường hợp assign không được',
    'description': '''
        Module này cải tiến quá trình assign stock moves.
        
        Tính năng:
        - Tự động tạo move line nếu assign fail
        - Xử lý trường hợp stock available nhưng không assign được
        - Log chi tiết assignment failures để debug
        - Fallback to partially_available nếu cần
        - Debug tool để kiểm tra lỗi trực tiếp
    ''',
    'author': 'HLV Team',
    'depends': ['stock'],
    'data': [
        'views/stock_picking_debug.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'external_dependencies': {},
}
