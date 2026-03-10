# Technical Documentation: HLV POS Return to Original Source Location

## Purpose
Override Odoo's default POS return behavior where all returns go to a fixed return location (usually `WH/Stock`). This module ensures returns go back to the specific location that shipped the product initially.

## Architecture

### Models
- `pos.order.line`: Inherited to override `_prepare_stock_move_vals`.

### Logic Flow
1. User creates a refund in POS.
2. POS Order is sync'd to backend.
3. `_create_order_picking` is called.
4. For each line, `_prepare_stock_move_vals` is executed.
5. If line quantity is negative and `refunded_orderline_id` is present:
    a. Locate the original `pos.order.line`.
    b. Find all completed `stock.move` records for the original order's pickings.
    c. Identify the move for the same product.
    d. Take that move's `location_id` (the original source).
    e. Set the current move's `location_dest_id` to that original source.

### POS IndexedDB Safeguard
- `static/src/js/idb_fix.js`: Automatically detects "NotFoundError" on object stores and deletes the `pos-db` in IndexedDB to force Odoo to rebuild the schema. This prevention system unblocks POS when models are removed or changed.

## File Structure
```
hlv_pos_return_source_location/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── pos_order.py
├── static/
│   └── src/
│       └── js/
│           └── idb_fix.js
└── TECHNICAL.md
```
