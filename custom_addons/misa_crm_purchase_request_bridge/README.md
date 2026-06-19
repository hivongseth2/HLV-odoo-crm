# MISA CRM Purchase Request Bridge

Creates Odoo `purchase.request` records from the MISA CRM purchase request detail page.

## Odoo setup

1. Install this addon: `misa_crm_purchase_request_bridge`.
2. Set system parameter `misa_crm_purchase_request_bridge.api_token` to a private token.
3. Endpoint used by the browser extension:

```text
POST /misa/crm/purchase-request/import
Header: X-Odoo-PR-Token: <token>
```

The importer prevents duplicates by searching `purchase.request.origin = PurchaseRequestNo`.
Products are resolved by `product.product.default_code` first, then by product name.

## Browser extension

Load `static/browser_extension` as an unpacked Chrome/Edge extension.
On a MISA CRM purchase request page, click `Tao YCMH Odoo`.
The extension asks once for the Odoo base URL and import token, then stores them in browser sync storage.
