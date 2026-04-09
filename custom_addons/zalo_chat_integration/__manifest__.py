# -*- coding: utf-8 -*-
# Copyright 2026 HLV
{
    'name': 'Zalo OA Chat Integration',
    'version': '18.0.1.0.0',
    'category': 'Tools/Communication',
    'summary': 'Two-way chat integration with Zalo Official Account',
    'description': """
        Zalo OA Chat Integration
        =========================
        
        This module enables two-way chat communication with Zalo Official Account:
        * Receive messages from customers via Zalo webhook
        * Send messages to customers directly from Odoo
        * Manage conversations per customer
        * Integration with Odoo Contact/CRM system
        * Track message history and conversation status
        
        Requires Zalo Official Account and App credentials.
    """,
    'author': 'HLV',
    'website': '',
    'depends': [
        'base',
        'mail',
        'contacts',
        'im_livechat',  # For Discuss chat UI
        'sale',  # For sale_order_id in evaluation
        'llm_tool',  # For LLM tool registration
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/zalo_chat_sequence.xml',
        'data/zalo_chat_cron.xml',
        'data/llm_tool_zalo_data.xml',
        'views/assets.xml',
        'views/product_alias_views.xml',
        'views/zalo_oa_config_views.xml',
        'views/zalo_chat_conversation_views.xml',
        'views/zalo_chat_message_views.xml',
        'views/res_partner_views.xml',
        'views/product_template_views.xml',
        'views/discuss_channel_views.xml',
        # 'views/zalo_customer_profile_views.xml',
        'views/zalo_chat_evaluation_views.xml',
        'views/zalo_chat_menu.xml',
        'wizards/send_zalo_chat_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
