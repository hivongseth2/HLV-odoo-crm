# -*- coding: utf-8 -*-
{
    'name': "Avoid Negative Stock",

    'summary': "Prevents products from having negative stock in Odoo.",

    'description': """
        This module prevents the confirmation of inventory moves or stock adjustments that would result in negative quantities. 
        It helps maintain inventory control and avoid accounting errors related to insufficient stock.
    """,

    'author': "BIT SYSTEMS, S.A.",
    'support': 'soporte@bitsysgt.com',
    'website': "https://bitsysgt.odoo.com",
    'license': 'LGPL-3',

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Inventory',
    'version': '18.0',

    # any module necessary for this one to work correctly
    'depends': ['base','stock'],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'views/product_template_views.xml',
    ],
    'images': ['static/description/banner.gif'], 
    # 'price': 0.00,
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}

