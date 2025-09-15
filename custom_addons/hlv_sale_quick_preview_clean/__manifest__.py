# -*- coding: utf-8 -*-
{
    'name': 'HLV Sale Quick Preview (Clean)',
    'version': '18.0.1.0.1',
    'summary': 'Quick preview panel for sale orders via contextual server action (no view override).',
    'category': 'Sales',
    'depends': ['base', 'web', 'sale'],
    'data': ['views/server_action.xml'],
    'assets': {
        'web.assets_backend': [
            'hlv_sale_quick_preview_clean/static/src/js/quick_panel.js',
            'hlv_sale_quick_preview_clean/static/src/css/quick_panel.css',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}