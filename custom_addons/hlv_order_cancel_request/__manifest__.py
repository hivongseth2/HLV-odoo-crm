{
    'name': 'Sales Order Cancellation Request',
    'version': '1.0',
    'summary': 'Allows sales to request order cancellation via a logged-in website page',
    'description': """
        This module allows salespeople to request order cancellation or modification via a website page that requires an Odoo login.
        Notifications are sent via Zalo to accountants and warehouse managers.
    """,
    'category': 'Sales',
    'author': 'Antigravity',
    'depends': ['sale', 'stock', 'website', 'hlv_zalo_zns'],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/cancel_request_view.xml',
        'views/website_templates.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
