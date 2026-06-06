{
    'name': 'Refine Contact Interface',
    'version': '18.0.2.0.0',
    'category': 'Sales/CRM',
    'summary': 'Refined contact classification, cleanup, merge and split workflows',
    'description': """
        Refines Contacts with practical customer/vendor/Shopee/MISA
        classification and controlled merge/split cleanup workflows.
    """,
    'author': 'Antigravity',
    'depends': ['base', 'contacts', 'sale', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'data/filter_tag_data.xml',
        'views/contact_operation_wizard_views.xml',
        'views/res_partner_views.xml',
        'data/ir_actions_server.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
}
