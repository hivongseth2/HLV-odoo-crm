{
    'name': 'Stock Picking Product Labels',
    'version': '18.0.1.0.0',
    'category': 'Inventory',
    'summary': 'In tem sản phẩm tùy chỉnh số lượng từ phiếu kho',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv', # Bạn nhớ tạo file này để cấp quyền truy cập
        'views/label_wizard_views.xml',
        'views/stock_picking_views.xml',
        'report/report_action.xml',
        'report/report_template.xml',
    ],
    'installable': True,
    'application': False,
}