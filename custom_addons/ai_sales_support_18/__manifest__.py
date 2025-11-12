# -*- coding: utf-8 -*-
{
    'name': 'AI Sales Support',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'AI-powered sales support with inventory check and supplier communication via Zalo',
    'description': """
AI Sales Support Module
=======================

This module provides AI-powered sales support functionality:

Features:
---------
* AI-powered product inquiry processing using ChatGPT
* Automatic inventory and pricing checks
* Supplier communication via Zalo OA when stock is insufficient
* Automated quotation generation
* Sales team interface for easy interaction

Workflow:
---------
1. Sales team sends product information and quantity to AI
2. AI checks inventory and pricing in Odoo database
3. If sufficient stock: Returns quotation immediately
4. If insufficient stock: Contacts suppliers via Zalo OA
5. AI processes supplier responses and generates final quotation

Requirements:
-------------
* ChatGPT API key
* Zalo OA account with verified user IDs for suppliers
    """,
    'author': 'HLV Team',
    'website': 'https://hoanglongvu.com',
    'depends': [
        'base',
        'sale',
        'stock',
        'product',
        'website',
        'contacts',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ai_sales_data.xml',
        'views/res_config_settings_views.xml',
        'views/ai_sales_views.xml',
        'views/supplier_contact_views.xml',
        'views/ai_sales_templates.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ai_sales_support_18/static/src/css/ai_sales.css',
            'ai_sales_support_18/static/src/js/ai_sales.js',
        ],
        'web.assets_backend': [
            'ai_sales_support_18/static/src/css/ai_sales_backend.css',
            'ai_sales_support_18/static/src/js/ai_sales_backend.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
}