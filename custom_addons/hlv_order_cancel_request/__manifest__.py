{
    'name': 'Sales Order Cancellation Request',
    'version': '1.0',
    'summary': 'Allows sales to request order cancellation via a public website page',
    'description': """
        This module allows salespeople to request order cancellation or modification via a password-protected website page.
        Notifications are sent via Zalo to accountants and warehouse managers.
    """,
    'category': 'Sales',
    'author': 'Antigravity',
    'depends': ['sale', 'website', 'hlv_zalo_zns'],
    'data': [
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
