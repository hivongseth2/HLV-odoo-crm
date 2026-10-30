# hlv_stock_overpick_guard

## Purpose
Prevents a picking from taking more than the actual on-hand stock at a source location, which would make stock negative.

The bug it fixes: a pick of 24 has only 22 on hand. In the detailed-operations dialog the user adds a line and picks the same 22 quant. A new 22 line is created and the old line drops to 0. The user then types 2 into the old line, so the picking shows 24 but stock goes to -2.
The onchange in `stock_move_line_quantity_limit` misses this because it only sees `_origin.quantity` of the line being edited (22 in the DB) and can't see the sibling line that hasn't been saved yet. This module adds a **server-side** check after save.

## Tree
```
hlv_stock_overpick_guard/
└── models/stock_picking.py   ← all logic (picking, move, move.line)
```

## Rule
For each open picking, group the open move lines (internal source location, storable product) by
`(product, location_id, lot, package, owner)`. Sum `quantity_product_uom` for each group; the sum must be ≤ the on-hand `quantity` of the quant with exactly that key (`_gather(strict=True)`, the same key `_action_done` uses to decrement stock).
Only the picking's own lines are counted. Reservations held by other pickings are ignored, because core frees those when this picking is validated.

## When the check runs
| Entry point | Behaviour |
|---|---|
| `stock.move._hlv_onchange_cap_overpick` (onchange `move_line_ids`, "Điều chuyển tồn kho" dialog) | **auto-reduces** before save: when a key's total exceeds on-hand, lines are reduced starting with those whose qty went up vs `_origin` (newest first), then a warning is shown. It only sees this move's lines; the save check below covers the rest |
| `stock.picking.write` (move/move-line/location vals) | runs super with context `hlv_overpick_defer`, then checks the whole picking once |
| `stock.move.write` (`move_line_ids`/`quantity`/`location_id`) | same as above, for the move's picking (this is where the "Điều chuyển tồn kho" dialog saves) |
| `stock.move.line.create/write` called directly (barcode, scripts) | checks only the keys of the changed lines; a write that only changes quantity checks only lines whose quantity went up |
| `stock.picking.button_validate` | re-checks before validating (stock may have changed since), counting only the lines core will process (picked logic) |

The defer context stops one2many commands from raising on an intermediate state, e.g. "create the new 22 line" running before "set the old line to 0".

## Bypass
Context `hlv_skip_overpick_check=True`, for data-fix scripts only.

## Extending
- To also check `transit` locations: add it to the `ml.location_id.usage == 'internal'` filter.
- To honour the per-product/category allow-negative flags from `stock_no_negative`: filter by them in `_hlv_check_overpick`.
