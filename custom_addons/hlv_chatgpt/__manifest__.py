{
    'name': 'HLV ChatGPT Manager',
    'version': '1.1',
    'summary': 'Chat AI quản lý sản phẩm MISA qua OpenAI Responses API (Stored Prompt)',
    'author': 'HLV',
    # misa_fetch_po_button cung cấp misa.api.utils / misa.config: mọi tool đều cần.
    'depends': ['base', 'product', 'stock', 'misa_fetch_po_button'],
    'external_dependencies': {'python': ['openai']},
    'data': [
        'security/chatgpt_security.xml',
        'security/ir.model.access.csv',
        'views/chatgpt_config_view.xml',
        'views/chatgpt_session_view.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_chatgpt/static/src/css/chat_style.css',
            'hlv_chatgpt/static/src/js/chat_widget.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
