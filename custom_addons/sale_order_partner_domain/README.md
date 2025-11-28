# Sale Order Partner Domain

## Description
This module customizes the domain of `partner_shipping_id` and `partner_invoice_id` fields in Sale Order to allow selecting both 'contact' and 'delivery' type partners.

## Features
- Allows selecting partners with type 'contact' or 'delivery'
- Only shows individual contacts (not companies)
- Shows contacts that are children of the selected customer or the customer itself

## Installation
1. Copy the module to your Odoo addons directory
2. Update the apps list
3. Install the "Sale Order Partner Domain" module

## Configuration
No configuration needed. The module works automatically after installation.

## Usage
After installation, when selecting delivery or invoice address in a sale order, you will see both 'contact' and 'delivery' type partners in the dropdown.
