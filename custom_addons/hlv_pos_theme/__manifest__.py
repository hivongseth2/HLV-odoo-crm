{
    'name': 'HLV POS Theme',
    'version': '18.0.1.0.1',
    'category': 'Point of Sale',
    'summary': 'Professional Sidebar Layout for Odoo 18 POS',
    'description': """
        Transforms the POS interface with a clean Sidebar Layout.
        Includes XML structure updates, robust CSS Grid layout, and JavaScript style cleanup.
    """,
    'author': 'HLV',
    'depends': ['point_of_sale'],
    'data': [],
    'assets': {
        # Using the standard asset bundle for Odoo 17/18 POS
        'point_of_sale._assets_pos': [
            'hlv_pos_theme/static/src/css/pos_theme.css',
            'hlv_pos_theme/static/src/xml/Screens/ProductScreen/ProductsWidget.xml',
            'hlv_pos_theme/static/src/js/category_button_patch.js',
        ],
    },
    'installable': True,
    'auto_install': False,
}
