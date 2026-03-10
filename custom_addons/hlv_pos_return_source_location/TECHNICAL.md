# Technical Documentation: HLV POS Return to Source Location

## Overview
This module ensures that when a product is returned (refunded) in Odoo POS, the stock move generated for the return is directed back to the original source location where the product was initially shipped from, instead of the default return location defined in the POS configuration.

## Key Components

### Backend Logic
- `models/pos_order.py`: Inherits `pos.order.line` and overrides `_prepare_stock_move_vals`.

### Logic Flow
1. When a POS order is validated, Odoo creates stock pickings.
2. For refund lines (quantity < 0), the system:
    a. Identifies the original order line using `refunded_orderline_id`.
    b. Finds the original `stock.move` records associated with that original line.
    c. Retrieves the `location_id` (Source Location) from the original move.
    d. Sets the `location_dest_id` (Destination Location) of the return move to this original source location.

## File Structure
```
hlv_pos_return_source_location/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── pos_order.py
└── TECHNICAL.md
```
