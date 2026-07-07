# HLV MISA Purchase Order Sync

Load unpacked extension:

```text
D:\HLV\HLV-odoo-crm\browser_extensions\hlv_misa_purchase_order_sync
```

Scope:

- Runs only on `https://amisapp.misa.vn/purchase/popup/purchaseorderdetail/*`.
- Reads the purchase order code from the disabled `DMH...` input/title.
- Enables `Sync qua Odoo` only when the page contains `Đã đồng bộ sang ứng dụng khác`.
- Queues Odoo sync through `/api/extension/po/sync`.
- Hooks the MISA button `Thu hồi trên ứng dụng khác`; after click, it queues `/api/extension/po/revoke`.

Settings are stored in Chrome sync storage:

- `odooBaseUrl`, for example `https://www.hoanglongvu-erp.com`
- `apiToken`, sent as `X-MISA-Token`

