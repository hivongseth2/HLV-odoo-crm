{
    'name': 'HLV POS Theme',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Clean and minimalist theme for Odoo POS',
    'description': """
        This module customizes the POS interface to replace the default colorful categories 
        with a cleaner, more professional look, implementing a Sidebar layout for categories.
    """,
    'author': 'HLV',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'data': [],
    'assets': {
        'point_of_sale._assets_pos': [
            'hlv_pos_theme/static/src/css/pos_theme.css',
            'hlv_pos_theme/static/src/xml/Screens/ProductScreen/ProductsWidget.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
