{
    'name': 'Production Assembly & Disassembly',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Simple production assembly and disassembly operations using Virtual Locations',
    'description': """
Production Assembly & Disassembly
==================================

This module provides a simple interface for warehouse/production operations:

Features:
---------
* Assembly: Input components to create finished products
* Disassembly: Break down finished products into components
* Uses Virtual Locations/Production (id=15) as intermediate location
* Based on stock moves without full MRP system
* Flexible component declaration per operation
* Automatic stock move generation and inventory updates

Operations:
-----------
* Assembly: Components → Virtual Location → Finished Product
* Disassembly: Finished Product → Virtual Location → Components

Interface:
----------
* List view showing operation number, date, type, main product, quantity, status
* Form view with operation details and component lines
* Simple buttons for processing operations
    """,
    'author': 'HLV Development Team',
    'website': 'https://hoanglongvu.com',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/production_operation_views.xml',
        'views/warehouse_access_config_views.xml',
        'views/menu_views.xml',
        'data/sequence_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'production_assembly/static/src/css/production_assembly.css',
        ],
    },
    'demo': [
        'data/demo_data.xml',
        'data/demo_warehouse_access.xml',
    ],
    # 'installable': True,  # TẠM TẮT ĐỂ BUILD
    'installable': False,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}