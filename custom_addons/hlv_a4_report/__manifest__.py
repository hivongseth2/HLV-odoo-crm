# -*- coding: utf-8 -*-
{
    'name': "hlv_a4_report",

    'summary': """
        Mẫu in Biên bản A4""",

    'description': """
        Module này cung cấp mẫu in Biên bản A4
    """,

    "author": "Your Company",
    "website": "http://www.yourcompany.com",
    "category": "Inventory",
    "version": "18.0.1.0.0",   
    "license": "LGPL-3",

    # any module necessary for this one to work correctly
    'depends': ['base', 'web', 'stock'],

    # always loaded
    'data': [
        'report/paperformat.xml',
        'report/bbgn_a4_khongngay.xml',
    ],
    "assets": {
        "web.report_assets_common": [
            'hlv_a4_report/static/fonts/times-new-roman.ttf',
            'hlv_a4_report/static/fonts/times-new-roman-bold.ttf',
            'hlv_a4_report/static/fonts/times-new-roman-italic.ttf',
            'hlv_a4_report/static/fonts/times-new-roman-bolditalic.ttf',
        ],
    },
}