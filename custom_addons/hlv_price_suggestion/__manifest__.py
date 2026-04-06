{
    'name': 'HLV AI Price Advisor',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Chatbot AI tư vấn giá bán dựa trên giá nhập, tồn kho, lượt bán',
    'description': """
        Chatbot AI hỗ trợ tư vấn giá bán sản phẩm:
        - Hỏi AI về giá bán nên đặt cho sản phẩm
        - AI phân tích căn cứ: giá nhập (PO), giá bán cho từng công ty (SO), tồn kho
        - Trả về lý luận chi tiết kèm dữ liệu minh chứng
        - Hỗ trợ xuất file Excel báo cáo đề xuất giá
    """,
    'author': 'HLV',
    'website': '',
    'depends': [
        'base',
        'product',
        'sale',
        'purchase',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/price_chat_views.xml',
        'views/price_chat_config_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_price_suggestion/static/src/scss/price_chat.scss',
            'hlv_price_suggestion/static/src/js/price_chat.js',
            'hlv_price_suggestion/static/src/xml/price_chat.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
