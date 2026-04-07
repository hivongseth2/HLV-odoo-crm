{
    'name': 'HLV Security Gateway',
    'version': '18.0.1.0.0',
    'summary': 'Block malicious requests and IPs at the Odoo level',
    'description': """
        This module provides an additional security layer for Odoo 18.
        - Blocks specific IP addresses.
        - Blocks common malicious patterns in URL paths (.php, .xml backup files, etc).
        - Returns 403 Forbidden for blacklisted requests.
    """,
    'author': 'Antigravity',
    'category': 'Administration',
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'views/security_rule_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
