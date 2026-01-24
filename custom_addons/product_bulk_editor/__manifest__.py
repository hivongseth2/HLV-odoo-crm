# -*- coding: utf-8 -*-
{
    'name': "Product Bulk Editor",
    'summary': "Excel-like interface for mass product editing",
    'description': """
        Provides a dedicated page for bulk updating of products.
        Features:
        - Editable list view (Excel-like)
        - Fields: Code, Name, Barcode, Prices (Public, Web, Listed, Commercial)
        - WordPress stock status with auto-sync
        - Search and Filter support
    """,
    'author': "Antigravity",
    'website': "http://www.yourcompany.com",
    'category': 'Sales',
    'version': '0.2',
    'depends': ['product', 'sale', 'stock', 'wordpress_sync'],
    'data': [
        'views/product_bulk_view.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
