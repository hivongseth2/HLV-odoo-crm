{
    'name': 'Stock Move Line Quantity Limit',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Prevent exceeding actual stock quantity when setting reserved quantities',
    'description': '''
        This module prevents users from entering reserved quantity (quantity) exceeding 
        the actual on-hand quantity at a location.
        
        Features:
        - Real-time validation on quantity field change
        - Database constraint to prevent invalid data
        - Warning popup when attempting to exceed stock
        - Automatic adjustment to available quantity
    ''',
    'author': 'HLV Team',
    'depends': ['stock'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
