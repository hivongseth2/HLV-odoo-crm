# Shopee Webhook Integration Technical Documentation

## Purpose
This module provides an integration with Shopee Webhooks to receive delivery status updates and automate relevant actions in Odoo.

## Directory Structure
```
shopee_webhook/
├── controllers/
│   └── main.py           # Webhook endpoints (/shopee/webhook/delivery)
├── models/
│   └── sale_order.py     # Extended Sale Order models with shopee status fields and notification logic
├── views/
│   └── sale_order_views.xml # UI enhancements for Shopee status
└── logs/                 # Persistent logs for webhook payloads
```

## Key Features

### 1. Webhook Endpoints
- `/shopee/webhook/delivery`: Receives status updates (code 3/4/...) and performs auto-fetch if order is missing.
- `/shopee/webhook/logs`: Admin view to inspect recent webhook activities.

### 2. Status Mapping
Shopee statuses are mapped to Vietnamese labels and displayed using badges on Sale Orders (for code 3 pushes).

### 3. Tracking Number Push
- Shopee `order_trackingno_push` (`code=4`) carries `data.ordersn`,
  `data.package_number`, and `data.tracking_no`.
- The webhook matches both `ordersn` and `shop_id`, then writes the latest
  `tracking_no` to both `carrier_tracking_ref` and `name` on the related
  outgoing picking. If several delivery pickings exist, the oldest active one
  is selected so picking names remain unique.
- Cancelled pickings are never updated. Active outgoing pickings are preferred;
  completed outgoing pickings are used only when no active picking remains.
- Code 4 requests must pass Shopee's `Authorization` HMAC-SHA256 check using the
  exact raw request body. Set `shopee_webhook.callback_url` when the public URL
  configured in Shopee differs from the URL seen by Odoo behind a reverse proxy.
- Operational pushes return HTTP 204 with an empty body. Verification requests
  still return the required `verify_info` JSON value.

### 4. Automatic Order Fetch (New)
- **Auto-Sync**: If a webhook arrives for an `ordersn` that is not yet in Odoo, the system automatically:
    1. Identifies the `shopee.shop` using `shop_id` from the payload.
    2. Calls Shopee API (Order Detail & Escrow Detail) using the shop's credentials.
    3. Builds and creates the `sale.order` in Odoo via `shopee_order_builder`.
    4. Continues to update the order status.

### 5. Automation & Notifications
- **Auto-validation**: Automatically validates pickings when status is `LOGISTICS_DELIVERY_DONE` (code 30).
- **Cancel Notification**: Sends a Zalo message to the warehouse when status is `CANCELLED`.
    - Uses configuration from `hlv_order_cancel_request`: `hlv_order_cancel_request.warehouse_zalo_mapping`.
    - Message is sent via `hlv.zalo.stock.notification` service.

## Integration Logic
- **Order Matching**: Attempt to match by `shopee_order_ref`, then Odoo name, then `client_order_ref`.
- **Auto-fetch Fallback**: If matching fails, triggers the API-based fetch if `shop_id` is present.
- **Dependencies**: Depends on `shopee_order_fetch` for API services and order building logic.
- **Zalo Notifications**: Uses a per-warehouse mapping to target the correct warehouse personnel based on the order's warehouse.
