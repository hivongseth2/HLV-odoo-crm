# -*- coding: utf-8 -*-

{
    "name": "Restrict Auto Save in Form View",
    "summary": "Disable automatic form saving and alert users about unsaved changes.",
    "description": """
        This module disables the automatic saving behavior of form views in Odoo 19, giving users full control over when their data is saved.
        
        When a user tries to leave a form view, refresh the page, or navigate elsewhere without explicitly saving their changes, 
        a warning popup is displayed. This prevents accidental data loss and ensures users consciously confirm their changes 
        before saving.
    
        Key Benefits:
        - Prevents unintended auto-save in form views
        - Displays a clear warning for unsaved changes
        - Improves data accuracy and user confidence
        - Fully compatible with Odoo 19

    """,
    "author": "CodeSphere Tech",
    "website": "https://www.codespheretech.in/",
    "category": 'Extra Tools',
    "version": "18.0.1.0.0",
    'sequence': 0,
    "currency": "USD",
    "price": "0",
    "depends": ['base', 'web'],
    "data": [],
    'assets': {
        'web.assets_backend': [
            'cst_restrict_auto_save_form/static/src/js/form_controller.js',
        ],
    },
    'images': ['static/description/Banner.png'],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
