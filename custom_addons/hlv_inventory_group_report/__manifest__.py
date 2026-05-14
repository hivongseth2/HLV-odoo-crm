{
    'name': 'HLV Báo cáo tồn kho theo nhóm',
    'version': '1.0',
    'category': 'Inventory',
    'summary': 'Báo cáo tồn kho theo nhóm sản phẩm tuỳ chỉnh',
    'description': """
        Cho phép gom nhóm sản phẩm và báo cáo tồn kho theo từng nhóm.
        Một sản phẩm có thể thuộc nhiều nhóm báo cáo.
        Hiển thị số lượng tồn tại từng kho và tổng tất cả kho.
        Xuất báo cáo dạng PDF hoặc xem trực tiếp trên trình duyệt.
    """,
    'author': 'HLV',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_report_group_views.xml',
        'views/inventory_report_wizard_views.xml',
        'report/inventory_report_template.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
