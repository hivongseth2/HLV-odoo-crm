{
    'name': 'Refine Contact Interface',
    'version': '18.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Clean up Contact interface by hiding child contacts by default',
    'description': """
        This module refines the Contacts interface to make it cleaner and more user-friendly.
        
        Features:
        - Adds a default filter "Main Contacts" (Liên hệ chính) to the Contacts view.
        - This filter hides subordinate addresses (Delivery, Invoice, etc.) which have a parent contact.
        - Users can still see child contacts by removing the filter or opening the parent contact.
    """,
    'author': 'Antigravity',
    'depends': ['base', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'data/filter_tag_data.xml',
        'views/res_partner_views.xml',
        'data/ir_actions_server.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
}
