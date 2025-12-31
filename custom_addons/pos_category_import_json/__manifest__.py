# -*- coding: utf-8 -*-
{
    'name': 'POS Category Import JSON',
    'version': '1.0',
    'category': 'Point of Sale',
    'summary': 'Import POS Categories from JSON file',
    'description': """
        Import POS Categories from JSON file, specifically designed for MISA format.
    """,
    'author': 'Antigravity',
    'depends': ['point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/pos_category_views.xml',
        'wizard/pos_category_import_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
