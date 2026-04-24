AxenorSuite: Show/Hide Print Actions
====================================

| Module for dynamic control of QWeb report print actions in Odoo.

Overview
--------
This module allows administrators to **dynamically show or hide QWeb report print actions** 
based on **Users** or **Companies**.  

It helps organizations maintain security, simplify user experience, 
and ensure that users only access the reports they are authorized to see.

Key Features
------------
- Show or hide reports **per User** or **per Company**.
- Works with **any ir.actions.report** (e.g., Sales Order, Delivery Slip, Invoice, etc.).
- **Configuration restricted to Settings/Administration users**.
- Reduces clutter in the "Print" dropdown by hiding irrelevant reports.
- Compatible with **Odoo 18.0 CE/EE**.

Use Cases
---------
- Restrict sensitive financial reports to finance department users only.
- In multi-company setups, show company-specific reports only.
- Provide department-wise reporting visibility (e.g., HR vs. Sales).

Configuration
-------------
1. Go to **Settings > Technical > Reports > Reports**.
2. Open a report (e.g., Sales Order / Delivery Slip).
3. Set the visibility rules for **Users** or **Companies**.
4. Only authorized users will see the "Print" action.

Technical Details
-----------------
- Extends ``ir.actions.report`` with additional access rules.
- Integrated with Odoo security and access control models.
- Safe and lightweight — no impact on existing reporting logic.

Installation
------------
1. Download the module and place it inside your custom addons path.
2. Update the Odoo app list.
3. Install the module **AxenorSuite: Show/Hide Print Actions**.

Dependencies
------------
- ``base``

Maintainer
----------
This module is developed and maintained by:

**AxenorSuite Consultancy Services LLP**  
Website: https://axenorsuite.com

License
-------
LGPL-3
