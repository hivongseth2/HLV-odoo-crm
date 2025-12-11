{
    'name': 'HLV ChatGPT Manager',
    'version': '1.0',
    'summary': 'Module quản lý và test kết nối OpenAI/ChatGPT',
    'author': 'HLV',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/chatgpt_config_view.xml',
        'views/chatgpt_session_view.xml',
    ],
    
    'assets': {
        'web.assets_backend': [
            'hlv_chatgpt/static/src/css/chat_style.css',
        ],
    },
    'installable': True,
    'application': True,
}