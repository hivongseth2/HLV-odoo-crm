# -*- coding: utf-8 -*-
{
    'name': "hlv_a4_report",

    'summary': """
        Short (1 phrase/line) summary of the module's purpose, used as
        subtitle on modules listing or apps.openerp.com""",

    'description': """
        Long description of module's purpose
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
        'report/paperformat.xml'
        'report/bbgn_a4_khongngay.xml'
    ],
}