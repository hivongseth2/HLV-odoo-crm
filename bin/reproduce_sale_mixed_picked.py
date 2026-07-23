# -*- coding: utf-8 -*-
"""
Reproduce the Odoo 18 mixed-picked validation behavior from a real sale order.

Run on Odoo.sh staging:

    odoo-bin shell -d <database> --no-http < bin/reproduce_sale_mixed_picked.py

Default test:
1. Copies SOURCE_SALE_ORDER_ID and confirms the copy.
2. Adds test stock through real Inventory Adjustment moves and forces one
   product to be reserved from two source bins.
3. Scans roughly half the products fully, one product partially from both
   source bins, and leaves the other products for backorder.
4. Replays the fixed HLV mobile finalizer (quantity + picked in one write).
5. Processes the Odoo backorder wizard and verifies quant deltas plus
   "done + backorder = original demand" for every product.

Set PARTIAL_BACKORDER_TEST=False for the full-picking test.
Set RUN_BROKEN_CONTROL_CASE=True to intentionally reproduce the old guard
failure before the fixed test.

This script intentionally changes staging data and stock.
"""

from collections import defaultdict
from datetime import datetime
import inspect

from odoo.tools.float_utils import float_compare


SOURCE_SALE_ORDER_ID = 39178
EXTRA_STOCK_FOR_FIRST_PRODUCTS = 5.0
EXTRA_PRODUCT_COUNT = 3
COMMIT_SETUP = True
VALIDATE_FIXED_CASE = True
COMMIT_FIXED_CASE = True
RUN_BROKEN_CONTROL_CASE = False
PARTIAL_BACKORDER_TEST = True
PARTIAL_SCAN_RATIO = 0.5
ALLOW_NON_STAGING = False


def _die(message):
    raise Exception(message)


def _verify_loaded_mobile_patch():
    try:
        from odoo.addons.hlv_mobile_barcode.controllers.picking_validate_controller import (
            HLVMobileBarcodePickingValidate,
        )

        source = inspect.getsource(HLVMobileBarcodePickingValidate.validate_picking)
        loaded_file = inspect.getsourcefile(HLVMobileBarcodePickingValidate)
    except Exception as error:
        print("WARNING: could not inspect loaded mobile controller: %s" % error)
        return

    has_fix = (
        "scanned_qty" in source
        and "'picked': float_compare(" in source
    )
    print("Loaded mobile controller: %s" % loaded_file)
    print("Loaded quantity + picked fix: %s" % has_fix)
    if not has_fix:
        _die(
            "The running Odoo process has not loaded the HLV mobile picked fix. "
            "Upgrade/restart the staging build before running this probe."
        )


def _is_storable(product):
    if "is_storable" in product._fields:
        return bool(product.is_storable)
    return product.type == "product"


def _qty_in_product_uom(move_line):
    return move_line.product_uom_id._compute_quantity(
        move_line.quantity,
        move_line.product_id.uom_id,
        round=False,
    )


def _print_move_state(picking, title):
    picking.invalidate_recordset()
    print("\n=== %s ===" % title)
    print(
        "picking id=%s name=%s state=%s backorder_mode=%s"
        % (
            picking.id,
            picking.name,
            picking.state,
            picking.picking_type_id.create_backorder,
        )
    )
    for move in picking.move_ids.sorted("id"):
        print(
            "MOVE id=%s product=%s demand=%s quantity=%s picked=%s state=%s"
            % (
                move.id,
                move.product_id.display_name,
                move.product_uom_qty,
                move.quantity,
                move.picked,
                move.state,
            )
        )
        for line in move.move_line_ids.sorted("id"):
            scanned = line.qty_scanned if "qty_scanned" in line._fields else "-"
            print(
                "  ML id=%s qty=%s qty_product_uom=%s scanned=%s picked=%s "
                "src=%s dest=%s lot=%s package=%s"
                % (
                    line.id,
                    line.quantity,
                    line.quantity_product_uom,
                    scanned,
                    line.picked,
                    line.location_id.complete_name,
                    line.location_dest_id.complete_name,
                    line.lot_id.name or "-",
                    line.package_id.name or "-",
                )
            )


def _quant_key(line, location, package):
    company = line.company_id or line.picking_id.company_id
    return (
        line.product_id.id,
        location.id,
        line.lot_id.id or False,
        package.id if package else False,
        line.owner_id.id or False,
        company.id if company else False,
    )


def _quant_snapshot(env2, picking):
    keys = set()
    for line in picking.move_line_ids:
        if not _is_storable(line.product_id) or line.quantity <= 0:
            continue
        if line.location_id.usage in ("internal", "transit"):
            keys.add(_quant_key(line, line.location_id, line.package_id))
        if line.location_dest_id.usage in ("internal", "transit"):
            keys.add(_quant_key(line, line.location_dest_id, line.result_package_id))

    values = {key: 0.0 for key in keys}
    if not keys:
        return values
    quants = env2["stock.quant"].sudo().search([
        ("product_id", "in", list({key[0] for key in keys})),
        ("location_id", "in", list({key[1] for key in keys})),
    ])
    for quant in quants:
        key = (
            quant.product_id.id,
            quant.location_id.id,
            quant.lot_id.id or False,
            quant.package_id.id or False,
            quant.owner_id.id or False,
            quant.company_id.id or False,
        )
        if key in values:
            values[key] += quant.quantity
    return values


def _print_quant_changes(env2, before, after):
    print("\n=== QUANT CHANGES ===")
    changed = 0
    for key in sorted(set(before) | set(after)):
        old = before.get(key, 0.0)
        new = after.get(key, 0.0)
        if abs(new - old) <= 1e-12:
            continue
        product = env2["product.product"].sudo().browse(key[0])
        location = env2["stock.location"].sudo().browse(key[1])
        print(
            "%s | %s | before=%s after=%s delta=%s"
            % (
                product.display_name,
                location.complete_name,
                old,
                new,
                new - old,
            )
        )
        changed += 1
    if not changed:
        print("No quant changed.")


def _copy_sale_order(env2, source):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    defaults = {
        "client_order_ref": "HLV_PICKED_PROBE_%s_FROM_%s" % (stamp, source.name),
    }

    # Avoid copying external marketplace identifiers with unique constraints.
    clear_fields = (
        "shopee_order_ref",
        "shopee_order_id",
        "x_studio_tham_chiu_shopee",
        "misa_order_id",
        "misa_refid",
    )
    for field_name in clear_fields:
        field = source._fields.get(field_name)
        if field and not field.required:
            defaults[field_name] = False

    context = dict(env2.context)
    context.update({
        "tracking_disable": True,
        "mail_create_nolog": True,
        "mail_notrack": True,
        "skip_shopee_auto_quality": True,
        "skip_misa_sale_sync": True,
    })
    clone = source.with_context(context).copy(default=defaults)
    print(
        "Cloned sale.order: source=%s(%s) clone=%s(%s)"
        % (source.name, source.id, clone.name, clone.id)
    )
    clone.with_context(context).action_confirm()
    return clone


def _find_pick_picking(clone):
    candidates = clone.picking_ids.filtered(
        lambda p: p.state not in ("done", "cancel")
        and (
            p.picking_type_id.sequence_code == "PICK"
            or "/PICK/" in (p.name or "")
        )
    ).sorted("id")
    if not candidates:
        candidates = clone.picking_ids.filtered(
            lambda p: p.state not in ("done", "cancel")
            and p.picking_type_id.code == "internal"
        ).sorted("id")
    if not candidates:
        _die("The cloned sale order did not create an open PICK transfer.")
    if len(candidates) > 1:
        print("PICK candidates: %s; using %s" % (candidates.mapped("name"), candidates[0].name))
    return candidates[0]


def _add_quant(env2, product, location, quantity):
    if quantity <= 0:
        return

    Quant = env2["stock.quant"].sudo().with_context(
        inventory_mode=True,
        inventory_name="HLV_PICKED_PROBE Inventory Adjustment",
    )
    previous_move_ids = env2["stock.move"].sudo().search([
        ("is_inventory", "=", True),
        ("product_id", "=", product.id),
        ("location_dest_id", "=", location.id),
    ]).ids
    quant = Quant.search([
        ("product_id", "=", product.id),
        ("location_id", "=", location.id),
        ("lot_id", "=", False),
        ("package_id", "=", False),
        ("owner_id", "=", False),
        ("company_id", "in", [False, location.company_id.id or env2.company.id]),
    ], limit=1)
    if quant:
        quant.write({
            "inventory_quantity": quant.quantity + quantity,
            "inventory_quantity_set": True,
        })
    else:
        quant = Quant.create({
            "product_id": product.id,
            "location_id": location.id,
            "inventory_quantity": quantity,
            "inventory_quantity_set": True,
        })

    result = quant.action_apply_inventory()
    if isinstance(result, dict):
        _die(
            "Inventory adjustment for %s at %s returned wizard %s."
            % (product.display_name, location.complete_name, result.get("res_model"))
        )
    inventory_move = env2["stock.move"].sudo().search([
        ("id", "not in", previous_move_ids),
        ("is_inventory", "=", True),
        ("product_id", "=", product.id),
        ("location_dest_id", "=", location.id),
        ("state", "=", "done"),
    ], order="id desc", limit=1)
    if not inventory_move:
        _die(
            "No completed Inventory Adjustment move was created for %s at %s."
            % (product.display_name, location.complete_name)
        )
    quant.invalidate_recordset()
    print(
        "Added test stock via Inventory Adjustment: product=%s location=%s "
        "delta=%s current=%s move=%s source=%s"
        % (
            product.display_name,
            location.complete_name,
            quantity,
            quant.quantity,
            inventory_move.id,
            inventory_move.location_id.complete_name,
        )
    )


def _ensure_stock_and_reservation(env2, clone, picking):
    stock_location = clone.warehouse_id.lot_stock_id or picking.location_id
    storable_lines = clone.order_line.filtered(
        lambda line: line.product_id and _is_storable(line.product_id)
    )

    # Add a visible buffer for a few products as requested.
    for product in storable_lines.mapped("product_id")[:EXTRA_PRODUCT_COUNT]:
        _add_quant(env2, product, stock_location, EXTRA_STOCK_FOR_FIRST_PRODUCTS)

    picking.action_assign()

    # Top up every remaining shortage so the probe tests picked, not availability.
    for move in picking.move_ids.filtered(
        lambda m: m.state not in ("done", "cancel") and _is_storable(m.product_id)
    ):
        rounding = move.product_uom.rounding
        shortage_move_uom = max(0.0, move.product_uom_qty - move.quantity)
        if float_compare(shortage_move_uom, 0.0, precision_rounding=rounding) <= 0:
            continue
        shortage_product_uom = move.product_uom._compute_quantity(
            shortage_move_uom,
            move.product_id.uom_id,
            round=False,
        )
        _add_quant(
            env2,
            move.product_id,
            stock_location,
            shortage_product_uom + move.product_id.uom_id.rounding,
        )

    picking.action_assign()
    unreserved = picking.move_ids.filtered(
        lambda m: (
            m.state not in ("done", "cancel")
            and _is_storable(m.product_id)
            and float_compare(
                m.quantity,
                m.product_uom_qty,
                precision_rounding=m.product_uom.rounding,
            ) < 0
        )
    )
    if unreserved:
        print("WARNING: moves still not fully reserved:")
        for move in unreserved:
            print(
                "  %s demand=%s reserved=%s"
                % (move.product_id.display_name, move.product_uom_qty, move.quantity)
            )


def _force_two_location_reservation(env2, clone, picking):
    stock_location = clone.warehouse_id.lot_stock_id or picking.location_id
    locations = env2["stock.location"].sudo().search([
        ("id", "child_of", stock_location.id),
        ("id", "!=", stock_location.id),
        ("usage", "=", "internal"),
        ("active", "=", True),
        "|",
        ("company_id", "=", False),
        ("company_id", "=", picking.company_id.id),
    ], order="id", limit=20)
    if len(locations) < 2:
        _die("Need at least two internal child locations under %s." % stock_location.complete_name)

    move = picking.move_ids.filtered(
        lambda m: (
            m.state not in ("done", "cancel")
            and _is_storable(m.product_id)
            and m.product_id.tracking == "none"
            and float_compare(
                m.product_uom_qty,
                2.0 * m.product_uom.rounding,
                precision_rounding=m.product_uom.rounding,
            ) > 0
        )
    ).sorted(key=lambda m: (-m.product_uom_qty, m.id))[:1]
    if not move:
        _die("Could not find an untracked move large enough for the multi-location test.")
    move = move[0]

    move.picked = False
    move._do_unreserve()

    first_qty = move.product_uom_qty / 2.0
    second_qty = move.product_uom_qty - first_qty
    selected_locations = locations[:2]
    for location, qty_move_uom in zip(selected_locations, (first_qty, second_qty)):
        qty_product_uom = move.product_uom._compute_quantity(
            qty_move_uom,
            move.product_id.uom_id,
            round=False,
        )
        _add_quant(
            env2,
            move.product_id,
            location,
            qty_product_uom + move.product_id.uom_id.rounding,
        )
        taken = move._update_reserved_quantity(
            qty_product_uom,
            location,
            strict=True,
        )
        if float_compare(
            taken,
            qty_product_uom,
            precision_rounding=move.product_id.uom_id.rounding,
        ) != 0:
            _die(
                "Could not reserve %s of %s at %s; reserved=%s."
                % (qty_product_uom, move.product_id.display_name, location.complete_name, taken)
            )

    move._recompute_state()
    move.invalidate_recordset()
    reserved_locations = move.move_line_ids.filtered(
        lambda ml: ml.quantity > 0
    ).mapped("location_id")
    if len(reserved_locations) < 2:
        _die(
            "Multi-location setup failed for %s; locations=%s."
            % (move.product_id.display_name, reserved_locations.mapped("complete_name"))
        )

    print(
        "Forced multi-location reservation: move=%s product=%s locations=%s"
        % (move.id, move.product_id.display_name, reserved_locations.mapped("complete_name"))
    )
    return move


def _prepare_mobile_quantities(picking):
    for line in picking.sudo().move_line_ids.filtered(
        lambda ml: ml.state not in ("done", "cancel")
    ):
        values = {}
        if "qty_scanned" in line._fields:
            values["qty_scanned"] = line.quantity
        if values:
            line.write(values)


def _prepare_partial_scan_plan(picking, multi_location_move):
    moves = picking.move_ids.filtered(
        lambda m: (
            m.state not in ("done", "cancel")
            and _is_storable(m.product_id)
            and m.quantity > 0
        )
    ).sorted("id")
    if len(moves) < 3:
        _die("Need at least three reserved moves for a meaningful partial/backorder test.")

    full_move_ids = set(moves[:max(1, len(moves) // 2)].ids)
    full_move_ids.discard(multi_location_move.id)

    plan = {}
    for move in moves:
        for line in move.move_line_ids.filtered(lambda ml: ml.quantity > 0):
            if move == multi_location_move:
                scanned_qty = line.quantity * PARTIAL_SCAN_RATIO
                mode = "partial-multi-location"
            elif move.id in full_move_ids:
                scanned_qty = line.quantity
                mode = "full"
            else:
                scanned_qty = 0.0
                mode = "backorder-only"
            line.qty_scanned = scanned_qty
            plan[line.id] = {
                "move_id": move.id,
                "product_id": move.product_id.id,
                "location_id": line.location_id.id,
                "reserved_qty": line.quantity,
                "scanned_qty": scanned_qty,
                "mode": mode,
            }

    scanned_multi_locations = {
        values["location_id"]
        for values in plan.values()
        if values["move_id"] == multi_location_move.id and values["scanned_qty"] > 0
    }
    if len(scanned_multi_locations) < 2:
        _die("The partial product was not scanned from at least two source locations.")

    print("\n=== PARTIAL SCAN PLAN ===")
    for move in moves:
        entries = [value for value in plan.values() if value["move_id"] == move.id]
        print(
            "move=%s product=%s mode=%s reserved=%s scanned=%s locations=%s"
            % (
                move.id,
                move.product_id.display_name,
                entries[0]["mode"],
                sum(value["reserved_qty"] for value in entries),
                sum(value["scanned_qty"] for value in entries),
                picking.env["stock.location"].browse(
                    sorted({value["location_id"] for value in entries})
                ).mapped("complete_name"),
            )
        )
    return plan


def _force_mixed_picked(picking):
    moves = picking.move_ids.filtered(
        lambda m: (
            m.state not in ("done", "cancel")
            and m.quantity > 0
            and m.move_line_ids
        )
    ).sorted("id")
    if len(moves) < 2:
        _die("Need at least two positive stock moves to reproduce mixed picked.")

    moves.picked = False
    picked_move = moves[0]
    picked_move.picked = True
    picking.invalidate_recordset()
    print(
        "Forced mixed picked: picked move=%s; unpicked moves=%s"
        % (
            picked_move.product_id.display_name,
            (moves - picked_move).mapped("product_id.display_name"),
        )
    )


def _apply_fixed_mobile_finalize(picking):
    """
    Replay the fixed PICK branch from
    hlv_mobile_barcode/controllers/picking_validate_controller.py.

    This intentionally uses qty_scanned as the source of truth. It does not
    mark reserved-but-unscanned lines as picked.
    """
    for line in picking.sudo().move_line_ids.filtered(
        lambda ml: ml.state not in ("done", "cancel")
    ):
        if line.quantity > 0:
            scanned_qty = line.qty_scanned
            line.write({
                "quantity": scanned_qty,
                "picked": float_compare(
                    scanned_qty,
                    0.0,
                    precision_rounding=line.product_uom_id.rounding,
                ) > 0,
            })
        elif line.qty_scanned:
            line.write({"qty_scanned": 0.0, "picked": False})
        elif line.picked:
            line.picked = False
    picking.invalidate_recordset()


def _validate_mixed_case(env2, picking):
    print("\n=== PHASE A: VALIDATE WITH MIXED PICKED ===")
    before = _quant_snapshot(env2, picking)
    result = None
    try:
        with env2.cr.savepoint():
            # skip_backorder reaches the exact _action_done filtering branch and
            # lets HLV_QUANT_GUARD prove that unpicked positive lines are skipped.
            result = picking.with_context(skip_backorder=True).button_validate()
            print("Mixed validate returned: %r" % (result,))
    except Exception as error:
        print("Mixed validate raised %s: %s" % (type(error).__name__, error))

    env2.invalidate_all()
    current = env2["stock.picking"].sudo().browse(picking.id)
    after = _quant_snapshot(env2, current)
    _print_move_state(current, "AFTER MIXED VALIDATE ATTEMPT")
    _print_quant_changes(env2, before, after)
    return current, result


def _validate_fixed_case(env2, picking):
    print("\n=== PHASE B: REPLAY FIXED HLV MOBILE FINALIZER ===")
    _apply_fixed_mobile_finalize(picking)
    _print_move_state(picking, "AFTER MOBILE FINALIZE / BEFORE VALIDATE")
    before = _quant_snapshot(env2, picking)
    result = picking.button_validate()
    print("Fixed validate returned: %r" % (result,))
    if isinstance(result, dict):
        print(
            "WARNING: validation returned wizard model=%s. The script will not auto-process it."
            % result.get("res_model")
        )
    env2.invalidate_all()
    current = env2["stock.picking"].sudo().browse(picking.id)
    after = _quant_snapshot(env2, current)
    _print_move_state(current, "AFTER FIXED VALIDATE")
    _print_quant_changes(env2, before, after)
    return current


def _process_backorder_wizard(env2, picking, action):
    wizard_context = dict(action.get("context") or {})
    wizard_context.setdefault("button_validate_picking_ids", picking.ids)
    wizard = env2["stock.backorder.confirmation"].with_context(wizard_context).create({
        "pick_ids": [(6, 0, picking.ids)],
        "backorder_confirmation_line_ids": [
            (0, 0, {"picking_id": picking.id, "to_backorder": True}),
        ],
    })
    return wizard.process()


def _validate_partial_backorder_case(env2, picking, multi_location_move, scan_plan):
    print("\n=== PARTIAL + MULTI-LOCATION BACKORDER VALIDATE ===")
    original_demand = defaultdict(float)
    product_rounding = {}
    for move in picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel")):
        demand_product_uom = move.product_uom._compute_quantity(
            move.product_uom_qty,
            move.product_id.uom_id,
            round=False,
        )
        original_demand[move.product_id.id] += demand_product_uom
        product_rounding[move.product_id.id] = move.product_id.uom_id.rounding

    _apply_fixed_mobile_finalize(picking)
    _print_move_state(picking, "AFTER PARTIAL MOBILE FINALIZE / BEFORE VALIDATE")

    positive_multi_lines = multi_location_move.move_line_ids.filtered(
        lambda ml: ml.quantity > 0 and ml.picked
    )
    if len(positive_multi_lines.mapped("location_id")) < 2:
        _die("Fixed finalizer lost one of the two scanned source locations.")

    expected_quant_delta = defaultdict(float)
    quant_rounding = {}
    for line in picking.move_line_ids.filtered(lambda ml: ml.quantity > 0 and ml.picked):
        product_qty = _qty_in_product_uom(line)
        source_key = _quant_key(line, line.location_id, line.package_id)
        dest_key = _quant_key(line, line.location_dest_id, line.result_package_id)
        if line.location_id.usage in ("internal", "transit"):
            expected_quant_delta[source_key] -= product_qty
            quant_rounding[source_key] = line.product_id.uom_id.rounding
        if line.location_dest_id.usage in ("internal", "transit"):
            expected_quant_delta[dest_key] += product_qty
            quant_rounding[dest_key] = line.product_id.uom_id.rounding

    before = _quant_snapshot(env2, picking)
    existing_backorder_ids = env2["stock.picking"].sudo().search([
        ("backorder_id", "=", picking.id),
    ]).ids

    action = picking.button_validate()
    print("Initial partial validate returned: %r" % (action,))
    if not isinstance(action, dict) or action.get("res_model") != "stock.backorder.confirmation":
        _die("Expected stock.backorder.confirmation, got %r." % (action,))

    wizard_result = _process_backorder_wizard(env2, picking, action)
    print("Backorder wizard process returned: %r" % (wizard_result,))
    env2.invalidate_all()

    current = env2["stock.picking"].sudo().browse(picking.id)
    backorders = env2["stock.picking"].sudo().search([
        ("backorder_id", "=", picking.id),
        ("id", "not in", existing_backorder_ids),
        ("state", "!=", "cancel"),
    ], order="id")
    if not backorders:
        _die("Validation completed without creating the expected backorder.")

    after = _quant_snapshot(env2, current)
    _print_move_state(current, "DONE PART OF PARTIAL TEST")
    for backorder in backorders:
        _print_move_state(backorder, "CREATED BACKORDER")
    _print_quant_changes(env2, before, after)

    quant_errors = []
    print("\n=== SCANNED QUANT DELTA CHECK ===")
    for key, delta in sorted(expected_quant_delta.items()):
        expected_qty = before.get(key, 0.0) + delta
        actual_qty = after.get(key, 0.0)
        product = env2["product.product"].browse(key[0])
        location = env2["stock.location"].browse(key[1])
        print(
            "%s | %s | before=%s delta=%s expected=%s actual=%s"
            % (
                product.display_name,
                location.complete_name,
                before.get(key, 0.0),
                delta,
                expected_qty,
                actual_qty,
            )
        )
        if float_compare(
            actual_qty,
            expected_qty,
            precision_rounding=quant_rounding[key],
        ) != 0:
            quant_errors.append("%s @ %s" % (product.display_name, location.complete_name))
    if quant_errors:
        _die("Scanned quant delta mismatch: %s" % quant_errors)

    done_qty = defaultdict(float)
    for move in current.move_ids.filtered(lambda m: m.state == "done"):
        done_qty[move.product_id.id] += move.product_uom._compute_quantity(
            move.quantity,
            move.product_id.uom_id,
            round=False,
        )

    backorder_demand = defaultdict(float)
    for move in backorders.move_ids.filtered(lambda m: m.state not in ("done", "cancel")):
        backorder_demand[move.product_id.id] += move.product_uom._compute_quantity(
            move.product_uom_qty,
            move.product_id.uom_id,
            round=False,
        )

    errors = []
    print("\n=== DEMAND BALANCE: DONE + BACKORDER = ORIGINAL ===")
    for product_id, planned_qty in sorted(original_demand.items()):
        accounted_qty = done_qty[product_id] + backorder_demand[product_id]
        product = env2["product.product"].browse(product_id)
        print(
            "%s | original=%s done=%s backorder=%s accounted=%s"
            % (
                product.display_name,
                planned_qty,
                done_qty[product_id],
                backorder_demand[product_id],
                accounted_qty,
            )
        )
        if float_compare(
            accounted_qty,
            planned_qty,
            precision_rounding=product_rounding[product_id],
        ) != 0:
            errors.append(product.display_name)

    if errors:
        _die("Demand balance mismatch for products: %s" % errors)

    multi_product_id = multi_location_move.product_id.id
    moved_locations = current.move_line_ids.filtered(
        lambda ml: (
            ml.product_id.id == multi_product_id
            and ml.state == "done"
            and ml.quantity > 0
        )
    ).mapped("location_id")
    if len(moved_locations) < 2:
        _die(
            "Done picking did not consume the partial product from two locations: %s"
            % moved_locations.mapped("complete_name")
        )

    print(
        "PARTIAL BACKORDER TEST PASSED: backorders=%s multi_location_product=%s locations=%s"
        % (
            backorders.mapped("name"),
            multi_location_move.product_id.display_name,
            moved_locations.mapped("complete_name"),
        )
    )
    return current, backorders


def _main(env2):
    dbname = env2.cr.dbname
    if not ALLOW_NON_STAGING and not any(term in dbname.lower() for term in ("stagin", "staging")):
        _die("Refusing to run on non-staging database: %s" % dbname)

    source = env2["sale.order"].sudo().browse(SOURCE_SALE_ORDER_ID).exists()
    if not source:
        _die("sale.order(%s) was not found." % SOURCE_SALE_ORDER_ID)
    if len(source.order_line.filtered(lambda line: _is_storable(line.product_id))) < 2:
        _die("Source sale order needs at least two storable products.")

    print("=== HLV MIXED PICKED SALE PROBE ===")
    print("DB=%s source=%s(%s)" % (dbname, source.name, source.id))
    _verify_loaded_mobile_patch()
    clone = _copy_sale_order(env2, source)
    picking = _find_pick_picking(clone)
    _ensure_stock_and_reservation(env2, clone, picking)
    multi_location_move = None
    scan_plan = None
    if PARTIAL_BACKORDER_TEST:
        multi_location_move = _force_two_location_reservation(env2, clone, picking)
    _prepare_mobile_quantities(picking)
    if PARTIAL_BACKORDER_TEST:
        picking.move_ids.picked = False
        scan_plan = _prepare_partial_scan_plan(picking, multi_location_move)
        _print_move_state(picking, "SETUP FOR PARTIAL + MULTI-LOCATION TEST")
    elif RUN_BROKEN_CONTROL_CASE:
        _force_mixed_picked(picking)
        _print_move_state(picking, "SETUP WITH MIXED PICKED")
    else:
        # Start from a clean pre-finalize state. Phase B must derive picked
        # entirely from qty_scanned, exactly like the patched mobile route.
        picking.move_ids.picked = False
        _print_move_state(picking, "SETUP BEFORE FIXED MOBILE FINALIZE")

    if COMMIT_SETUP:
        env2.cr.commit()
        print("\nCommitted setup. Clone and added stock are now visible in staging.")
    else:
        print("\nCOMMIT_SETUP=False; setup remains in the current transaction.")

    backorders = env2["stock.picking"]
    if RUN_BROKEN_CONTROL_CASE and not PARTIAL_BACKORDER_TEST:
        picking, _result = _validate_mixed_case(env2, picking)

    if VALIDATE_FIXED_CASE:
        if PARTIAL_BACKORDER_TEST:
            picking, backorders = _validate_partial_backorder_case(
                env2,
                picking,
                multi_location_move,
                scan_plan,
            )
        else:
            picking = _validate_fixed_case(env2, picking)
        if COMMIT_FIXED_CASE:
            env2.cr.commit()
            print("\nCommitted fixed validation.")
        else:
            env2.cr.rollback()
            print("\nRolled back fixed validation.")

    print("\n=== RESULT ===")
    print("clone sale.order id=%s name=%s" % (clone.id, clone.name))
    print("PICK id=%s name=%s state=%s" % (picking.id, picking.name, picking.state))
    if backorders:
        print("Backorders=%s states=%s" % (backorders.mapped("name"), backorders.mapped("state")))
    if RUN_BROKEN_CONTROL_CASE:
        print("Review HLV_QUANT_GUARD logs/chatter for the intentional phase A failure.")
    elif PARTIAL_BACKORDER_TEST:
        print("Partial + multi-location fix test completed.")
    else:
        print("Fix-only mode completed without an intentional guard failure.")


_main(env)
