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
    'depends': ['base', 'web', 'stock', 'sale', 'purchase'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'report/paperformat.xml',
        'report/bbgn_a4_khongngay.xml',
        'report/bbgn_a4_khong_gia.xml',
        'report/pxbh_khachle_khonghd.xml',
        'report/bbbg_a4_co_po.xml',
        'views/bbgn_date_wizard_views.xml',
        'report/print_proxy.xml',
        'report/px_hlv_a4.xml',
        'report/px_hlv_a4_batch.xml',
        'report/bbgn_a5_khongngay.xml',
        'report/pxbh_khachle_khonghd_a5.xml',
        'report/px_hlv_a5.xml',
        'report/bbbg_a5_co_po.xml',
        'report/bbgn_a5_khong_gia.xml',
    ],
}