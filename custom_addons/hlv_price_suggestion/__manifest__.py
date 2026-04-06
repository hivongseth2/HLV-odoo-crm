{
    'name': 'HLV Price Suggestion (AI)',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Đề xuất giá bán thông minh dựa trên giá nhập, tồn kho, lượt bán và AI',
    'description': """
        Module đề xuất giá bán cho sản phẩm dựa trên:
        - Giá nhập từ đơn mua hàng (Purchase Order)
        - Giá bán theo từng công ty (Company-specific pricing)
        - Số lượng tồn kho hiện tại
        - Lượt bán (tốc độ bán hàng)
        - Tình trạng hàng từ nhà cung cấp
        - Phân tích AI (OpenAI) để đề xuất giá tối ưu
    """,
    'author': 'HLV',
    'website': '',
    'depends': [
        'base',
        'mail',
        'product',
        'sale',
        'purchase',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/price_suggestion_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
