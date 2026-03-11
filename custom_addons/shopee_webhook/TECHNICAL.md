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
- `/shopee/webhook/delivery`: Receives status updates (code 23/30).
- `/shopee/webhook/logs`: Admin view to inspect recent webhook activities.

### 2. Status Mapping
Shopee statuses are mapped to Vietnamese labels and displayed using badges on Sale Orders.

### 3. Automation & Notifications
- **Auto-validation**: Automatically validates pickings when status is `LOGISTICS_DELIVERY_DONE` (code 30).
- **Cancel Notification**: Sends a Zalo message to the warehouse when status is `CANCELLED`.
    - Uses configuration from `hlv_order_cancel_request`: `hlv_order_cancel_request.warehouse_zalo_mapping`.
    - Message is sent via `hlv.zalo.stock.notification` service.

## Integration Logic
- **Order Matching**: Attempt to match by `shopee_order_ref`, then Odoo name, then `client_order_ref`. If still not found, tries matching by tracking number in `stock.picking`.
- **Zalo Notifications**: Uses a per-warehouse mapping to target the correct warehouse personnel based on the order's warehouse.
