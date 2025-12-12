# -*- coding: utf-8 -*-
{
    'name': 'HLV ChatGPT Manager',
    'version': '18.0.2.0.0',
    'summary': 'Chat AI Multi-Agent (Router + Specialists) sử dụng Prompt ID',
    'author': 'HLV',
    'depends': ['base', 'product', 'stock'],
    'data': [
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