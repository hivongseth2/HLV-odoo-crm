# -*- coding: utf-8 -*-
{
    "name": "AxenorSuite: Show/Hide Print Actions",
    "summary": "Dynamically control visibility of QWeb report print actions by User or Company.",
    "description": """
AxenorSuite: Show/Hide Print Actions
=====================================

This module provides flexible control over Odoo QWeb report print actions.

Key Features:
-------------
- Dynamically **show or hide reports** for specific Users or Companies.
- Works with **any ir.actions.report** (e.g., Sales Order, Delivery Slip, Invoices, etc.).
- Easy configuration from the backend — only accessible to Settings/Administration users.
- Ensures users only see the reports relevant to their role and company.
- Improves system security and reduces clutter in the "Print" dropdown.

Use Cases:
----------
- Hide sensitive financial reports for non-finance users.
- Restrict company-specific reports in multi-company environments.
- Provide different reporting visibility for different departments.

Technical Information:
----------------------
- Extends `ir.actions.report` with new access configuration.
- Integrated with Odoo security rules and access control.
- Fully compatible with Odoo CE/EE v18.0.

""",
    "version": "18.0.0.1.0",
    "license": "LGPL-3",
    "author": "AxenorSuite Consultancy Services LLP",
    "website": "https://axenorsuite.com",
    "category": "Administration/Reporting",
    "depends": ["base"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/report_access_right_view.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
