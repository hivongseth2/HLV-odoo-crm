{
    'name': 'HLV POS Theme',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Professional Sidebar Layout for Odoo 18 POS',
    'description': """
        Transforms the POS interface:
        1. Vertical Sidebar for Categories (Left Side).
        2. Clean, consistent Left-Aligned styling.
        3. Removes color clutter.
    """,
    'author': 'HLV',
    'depends': ['point_of_sale'],
    'data': [],
    'assets': {
        'point_of_sale._assets_pos': [
            'hlv_pos_theme/static/src/js/category_button_patch.js',
            'hlv_pos_theme/static/src/css/pos_theme.css',
        ],
    },
    'installable': True,
    'auto_install': False,
}
