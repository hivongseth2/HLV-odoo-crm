{
    'name': 'Milwaukee Website Embedded',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Nhúng website Milwaukee vào Odoo thông qua Iframe (OWL 2.0 Client Action)',
    'description': '',
    'author': 'Hoang Long Vu',
    'depends': ['product', 'mail', 'stock', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/milwaukee_master_views.xml',
        'views/milwaukee_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_milwaukee_embedded/static/src/xml/milwaukee_iframe.xml',
            'hlv_milwaukee_embedded/static/src/js/milwaukee_iframe.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
