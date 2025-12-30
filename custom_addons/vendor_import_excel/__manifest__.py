
{
    'name': 'Vendor Import Excel',
    'version': '1.0',
    'summary': 'Import/Update Vendors from Excel',
    'description': """
        Update vendor info from Excel file based on Name.
        Updates: company_registry (ref), street, vat, phone, mobile.
        Sets is_company=True if name contains "Công ty".
    """,
    'category': 'Tools',
    'author': 'Antigravity',
    'depends': ['base', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/vendor_import_wizard.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
