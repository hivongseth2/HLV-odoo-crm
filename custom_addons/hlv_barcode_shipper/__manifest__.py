# -*- coding: utf-8 -*-
{
    'name': 'HLV Barcode Shipper',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Mobile barcode scanning for shippers to process delivery orders',
    'description': """
HLV Barcode Shipper Module
==========================

This module provides a mobile-optimized interface for shippers to scan barcodes 
and process delivery orders efficiently.

Features:
---------
* Scan PICK order barcodes to find related OUT orders
* Display package lists (PACK) or product lists for OUT orders
* Track scanned packages with scanned status
* Complete delivery with automatic validation
* Mobile-optimized interface with barcode widget
* REST API endpoints for barcode operations
* Shipper security group with limited permissions
* Optional scan logging for audit trail

Workflow:
---------
1. Shipper scans PICK order barcode (PICKxxxxx)
2. System finds related OUT order automatically
3. Display packages (PACKxxx) or products with scan status
4. Shipper scans each package/product
5. When all items scanned, "Complete Delivery" button appears
6. Complete delivery validates the OUT order (DONE status)
7. Alternative: Re-scan PICK barcode to complete directly

API Endpoints:
--------------
* /api/barcode/scan_pick - Scan PICK order
* /api/barcode/get_out - Get OUT order details
* /api/barcode/scan_package - Scan package/product
* /api/barcode/complete_out - Complete delivery order
    """,
    'author': 'HLV Development Team',
    'website': 'https://hoanglongvu.com',
    'depends': [
        'base',
        'stock',
        'barcodes',
        'web',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/barcode_shipper_views.xml',
        'views/barcode_scan_log_views.xml',
        'views/stock_picking_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_barcode_shipper/static/src/js/barcode_scanner.js',
            'hlv_barcode_shipper/static/src/css/barcode_shipper.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}