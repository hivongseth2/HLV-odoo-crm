{
    'name': 'HLV Stock Picking Print Sequence',
    'version': '18.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Sắp xếp thứ tự in biên bản đi / Delivery Order',
    'description': '''
        Module tính năng sắp xếp thứ tự in những biên bản đi.
        
        Tính năng chính:
        - Thêm trường sequence (thứ tự) cho stock.picking
        - Có thể kéo thả để sắp xếp thứ tự in
        - Hỗ trợ in theo thứ tự đã sắp xếp
        - Tự động đánh số thứ tự in hàng loạt
        
        Hướng dẫn sử dụng:
        1. Vào Inventory > Picking Operations > Delivery Orders
        2. Kéo thả hoặc nhập trực tiếp số thứ tự trong cột "Print Sequence"
        3. Click "Print Selected" để in theo thứ tự
    ''',
    'depends': ['stock', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_picking_views.xml',
        'views/wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
