# MISA CRM Purchase Request Extension

Load this folder directly as an unpacked Chrome/Edge extension:

```text
D:\HLV\HLV-odoo-crm\custom_addons\misa_crm_purchase_request_bridge
```

The extension reads the current MISA CRM purchase request page, reads `localStorage.AMIS.CRM_token`, and posts the payload to Odoo.

Odoo endpoint addon is separated at:

```text
custom_addons/misa_crm_purchase_request_endpoint
```