{
    'name': 'HLV ChatGPT Manager',
    'version': '1.0',
    'summary': 'Chat AI Multi-Agent (Router + Specialists) sử dụng Prompt ID',
    'author': 'HLV',
    # im_livechat + mail: bridge Live Chat (website widget) -> hlv_chatgpt -> auto-reply back to the livechat channel
    'depends': ['base', 'product', 'stock', 'mail', 'im_livechat', 'misa_crm_tool'],
    'data': [
        'security/ir.model.access.csv',
        'views/im_livechat_channel_view.xml',
        'views/chatgpt_config_view.xml',
        'views/chatgpt_session_view.xml',
        'views/chatgpt_tag_view.xml',
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

    # Auto-enable livechat AI on existing channels after upgrade/install
    'post_init_hook': 'post_init_hook',
}
