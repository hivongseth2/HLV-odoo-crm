{
    'name': 'HLV Report Print Template Sequence Manager',
    'version': '18.0.1.0.0',
    'category': 'Tools',
    'summary': 'Manage and reorder print template order in dropdown menus',
    'description': '''
        This module allows you to control the order of print templates
        (reports) that appear in the print dropdown menu. You can easily
        reorder templates to put your most-used reports at the top.
        
        Features:
        - Add sequence field to print templates
        - Drag-and-drop reordering
        - Group templates by model
        - Quick access menu to manage templates
    ''',
    'author': 'HLV',
    'depends': ['stock', 'web'],
    'data': [
        'views/ir_actions_report_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
