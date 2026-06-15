#!/usr/bin/env python3
"""
Run inside Odoo shell:

    python odoo-bin shell -d <DB_NAME> --no-http < bin/check_delivery_combo_stock.py

Optional override:

    CHECK_SO=DH125524949232834 python odoo-bin shell -d <DB_NAME> --no-http < bin/check_delivery_combo_stock.py
"""

import os
import inspect


ORDER_NAME = os.environ.get("CHECK_SO", "DH125524949232834").strip()
ACTIVE_STATES = ("waiting", "confirmed", "assigned", "partially_available")


def qty(v):
    return float(v or 0.0)


def line(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def find_so():
    SaleOrder = env["sale.order"].sudo()
    so = SaleOrder.search([("name", "=", ORDER_NAME)], limit=1)
    if not so:
        so = SaleOrder.search([("client_order_ref", "=", ORDER_NAME)], limit=1)
    if not so:
        so = SaleOrder.search([("origin", "ilike", ORDER_NAME)], limit=1)
    return so


def child_internal_locations(root):
    if not root:
        return env["stock.location"].sudo().browse()
    return env["stock.location"].sudo().search([
        ("id", "child_of", root.id),
        ("usage", "=", "internal"),
    ])


def quant_totals(product, locations):
    if not product or not locations:
        return {"qty": 0.0, "reserved": 0.0, "free": 0.0, "rows": []}
    rows = env["stock.quant"].sudo().search([
        ("product_id", "=", product.id),
        ("location_id", "in", locations.ids),
    ])
    result = {"qty": 0.0, "reserved": 0.0, "free": 0.0, "rows": []}
    for q in rows:
        q_qty = qty(q.quantity)
        q_res = qty(q.reserved_quantity)
        result["qty"] += q_qty
        result["reserved"] += q_res
        result["free"] += max(q_qty - q_res, 0.0)
        if q_qty or q_res:
            result["rows"].append(q)
    return result


def find_phantom_bom(product):
    if not product:
        return env["mrp.bom"].sudo().browse()
    boms = env["mrp.bom"].sudo().search([
        ("type", "=", "phantom"),
        ("product_tmpl_id", "=", product.product_tmpl_id.id),
        "|",
        ("product_id", "=", False),
        ("product_id", "=", product.id),
    ])
    exact = boms.filtered(lambda b: b.product_id.id == product.id)
    return (exact or boms)[:1]


def active_moves_for_sale_line(sale_line):
    return sale_line.move_ids.filtered(lambda m: m.state not in ("cancel", "done"))


def reserved_for_sale_line_product(sale_line, product):
    return sum(qty(m.quantity) for m in active_moves_for_sale_line(sale_line) if m.product_id.id == product.id)


def print_scope(label, product, locations):
    totals = quant_totals(product, locations)
    print(
        "  %-18s qty=%8.2f reserved=%8.2f free=%8.2f locations=%s"
        % (label, totals["qty"], totals["reserved"], totals["free"], len(locations))
    )
    for q in sorted(totals["rows"], key=lambda x: x.location_id.complete_name):
        print(
            "      %-70s qty=%8.2f reserved=%8.2f free=%8.2f"
            % (
                q.location_id.complete_name,
                qty(q.quantity),
                qty(q.reserved_quantity),
                max(qty(q.quantity) - qty(q.reserved_quantity), 0.0),
            )
        )
    return totals


def print_moves(sale_line, products):
    product_ids = set(p.id for p in products if p)
    moves = active_moves_for_sale_line(sale_line).filtered(lambda m: m.product_id.id in product_ids)
    if not moves:
        print("  Active moves for this sale line: none")
        return
    print("  Active moves for this sale line:")
    for m in moves.sorted("id"):
        print(
            "    move=%s state=%s product=%s qty=%s demand=%s picking=%s seq=%s"
            % (
                m.id,
                m.state,
                m.product_id.display_name,
                qty(m.quantity),
                qty(m.product_uom_qty),
                m.picking_id.name or "",
                (m.picking_id.picking_type_id.sequence_code or "").upper(),
            )
        )
        print("      src=%s" % (m.location_id.complete_name or ""))
        print("      dst=%s" % (m.location_dest_id.complete_name or ""))


def kit_availability_from_components(bom, sale_line, scope_locations, scope_label, cap_by_on_hand):
    kit_qty = float("inf")
    details = []
    bom_qty = qty(bom.product_qty) or 1.0
    for comp in bom.bom_line_ids:
        component = comp.product_id
        per_kit = qty(comp.product_qty) / bom_qty
        if not component or per_kit <= 0:
            continue
        totals = quant_totals(component, scope_locations)
        reserved_here = reserved_for_sale_line_product(sale_line, component)
        effective = totals["free"] + reserved_here
        if cap_by_on_hand:
            effective = min(effective, totals["qty"])
        possible = effective / per_kit
        kit_qty = min(kit_qty, possible)
        details.append((component, per_kit, totals, reserved_here, effective, possible))
    if kit_qty == float("inf"):
        kit_qty = 0.0
    print("  Kit availability in %-14s cap_by_on_hand=%s => %.2f kit" % (scope_label, cap_by_on_hand, kit_qty))
    for component, per_kit, totals, reserved_here, effective, possible in details:
        print(
            "    comp=%s per_kit=%.2f qty=%.2f free=%.2f reserved_for_so=%.2f effective=%.2f possible_kit=%.2f"
            % (
                component.display_name,
                per_kit,
                totals["qty"],
                totals["free"],
                reserved_here,
                effective,
                possible,
            )
        )
    return kit_qty


so = find_so()
if not so:
    print("ERROR: Sale order not found: %s" % ORDER_NAME)
    raise SystemExit(1)

wh = so.warehouse_id
lot_root = wh.lot_stock_id if wh else False
view_root = (wh.view_location_id or wh.lot_stock_id) if wh else False
lot_locs = child_internal_locations(lot_root)
view_locs = child_internal_locations(view_root)

line("SALE ORDER")
print("SO: %s id=%s state=%s partner=%s" % (so.name, so.id, so.state, so.partner_id.display_name))
print("Warehouse: %s id=%s" % (wh.display_name if wh else "", wh.id if wh else ""))
print("lot_stock_id:  %s id=%s" % (lot_root.complete_name if lot_root else "", lot_root.id if lot_root else ""))
print("view_location: %s id=%s" % (view_root.complete_name if view_root else "", view_root.id if view_root else ""))
print("lot internal location count:  %s" % len(lot_locs))
print("view internal location count: %s" % len(view_locs))

line("PICKINGS")
for p in so.picking_ids.sorted(lambda p: (p.create_date, p.id)):
    print(
        "Picking %s id=%s state=%s code=%s seq=%s printed=%s return=%s backorder=%s"
        % (
            p.name,
            p.id,
            p.state,
            p.picking_type_code,
            (p.picking_type_id.sequence_code or "").upper(),
            bool(getattr(p, "x_printed", False)),
            p.return_id.name or "",
            p.backorder_id.name or "",
        )
    )

line("SALE LINES / STOCK")
for sol in so.order_line:
    if sol.display_type or not sol.product_id:
        continue
    product = sol.product_id
    bom = find_phantom_bom(product)
    is_kit = bool(bom)
    pending = qty(sol.product_uom_qty) - qty(sol.qty_delivered)

    print("\nSOL %s product=%s" % (sol.id, product.display_name))
    print(
        "  ordered=%.2f delivered=%.2f pending=%.2f type=%s is_phantom_kit=%s"
        % (qty(sol.product_uom_qty), qty(sol.qty_delivered), pending, product.type, is_kit)
    )
    if is_kit:
        print(
            "  BOM: %s id=%s product_qty=%.2f product_id=%s"
            % (bom.display_name, bom.id, qty(bom.product_qty), bom.product_id.display_name or "")
        )
        components = [c.product_id for c in bom.bom_line_ids if c.product_id]
        print_moves(sol, components)
        print("  Component stock by scope:")
        for comp in bom.bom_line_ids:
            if not comp.product_id:
                continue
            print("  - component: %s" % comp.product_id.display_name)
            print_scope("OLD lot_stock", comp.product_id, lot_locs)
            print_scope("NEW view_loc", comp.product_id, view_locs)
        print("  Module-style kit calculation:")
        kit_availability_from_components(bom, sol, lot_locs, "OLD lot_stock", cap_by_on_hand=True)
        kit_availability_from_components(bom, sol, view_locs, "NEW view_loc", cap_by_on_hand=True)
        print("  Drawer formatter-style kit calculation:")
        kit_availability_from_components(bom, sol, lot_locs, "OLD lot_stock", cap_by_on_hand=False)
        kit_availability_from_components(bom, sol, view_locs, "NEW view_loc", cap_by_on_hand=False)
    else:
        print_moves(sol, [product])
        old_totals = print_scope("OLD lot_stock", product, lot_locs)
        new_totals = print_scope("NEW view_loc", product, view_locs)
        reserved_here = reserved_for_sale_line_product(sol, product)
        old_effective = min(old_totals["free"] + reserved_here, old_totals["qty"])
        new_effective = min(new_totals["free"] + reserved_here, new_totals["qty"])
        print("  reserved_for_so=%.2f" % reserved_here)
        print("  effective OLD lot_stock=%.2f" % old_effective)
        print("  effective NEW view_loc=%.2f" % new_effective)

line("DASHBOARD RPC QUICK CHECK")
try:
    data = env["sale.order"].sudo().get_delivery_dashboard_data(
        search_query=so.name,
        filter_warehouse_id=str(wh.id) if wh else "all",
        limit=5,
        offset=0,
        show_completed=True,
        include_stats=False,
    )
    orders = data.get("orders") or []
    print("orders returned: %s" % len(orders))
    for order in orders:
        print(
            "  %s stock_status=%s packing_status=%s real_delivery_status=%s"
            % (
                order.get("name"),
                order.get("stock_status"),
                order.get("packing_status"),
                order.get("real_delivery_status"),
            )
        )
        for ldata in order.get("lines") or []:
            pname = ldata.get("product_id")[1] if ldata.get("product_id") else ""
            eff_stock = qty(ldata.get("qty_warehouse_free")) + qty(ldata.get("qty_reserved_here"))
            print(
                "    line=%s kit=%s ordered=%.2f delivered=%.2f packed=%.2f wh_free=%.2f reserved=%.2f eff_stock=%.2f"
                % (
                    pname,
                    ldata.get("is_kit"),
                    qty(ldata.get("product_uom_qty")),
                    qty(ldata.get("qty_delivered")),
                    qty(ldata.get("qty_packed")),
                    qty(ldata.get("qty_warehouse_free")),
                    qty(ldata.get("qty_reserved_here")),
                    eff_stock,
                )
            )
except Exception as exc:
    print("Dashboard RPC check failed: %s" % exc)

line("DIRECT FORMATTER CHECK")
try:
    service = env["hlv.delivery.planner.service"].sudo()
    formatter_src = inspect.getsource(type(service)._format_dashboard_order)
    service_src = inspect.getsource(type(service).get_dashboard_data)
    print("runtime formatter has by_product map support: %s" % ("by_product" in formatter_src))
    print("runtime service has by_product map support: %s" % ("by_product" in service_src))

    page_tmpl_ids = so.order_line.mapped("product_id.product_tmpl_id").ids
    page_kits = env["mrp.bom"].sudo().search([
        ("product_tmpl_id", "in", page_tmpl_ids),
        ("type", "=", "phantom"),
    ]) if page_tmpl_ids else env["mrp.bom"].sudo().browse()
    page_kit_tmpl_ids = set(page_kits.mapped("product_tmpl_id").ids)
    page_kit_bom_map = {"by_product": {}, "by_template": {}}
    for kbom in page_kits:
        if kbom.product_id:
            page_kit_bom_map["by_product"][kbom.product_id.id] = kbom
        else:
            page_kit_bom_map["by_template"].setdefault(kbom.product_tmpl_id.id, kbom)
    print("page_kits found: %s" % len(page_kits))
    for kbom in page_kits:
        print(
            "  bom id=%s tmpl=%s product=%s components=%s"
            % (
                kbom.id,
                kbom.product_tmpl_id.display_name,
                kbom.product_id.display_name or "(template)",
                ", ".join(
                    "%s x %.2f" % (bl.product_id.display_name, qty(bl.product_qty))
                    for bl in kbom.bom_line_ids
                ),
            )
        )

    _sales, _matched_ids, _stats, product_availabilities, product_on_hand, so_status_dict = (
        service._calculate_po_and_stock_status(
            so,
            "",
            "",
            "all",
            "all",
            "all",
            "all",
            show_completed=True,
            filter_need_transfer=False,
            filter_new_orders=False,
        )
    )
    direct_order = service._format_dashboard_order(
        so,
        service._fetch_pos_for_sales(so),
        product_availabilities,
        product_on_hand,
        service._fetch_attachments_for_pickings(so.mapped("picking_ids").ids),
        service._fetch_packages_for_sales(so),
        so_status_dict.get(so.id, {}),
        transfer_suggestions=[],
        page_kit_tmpl_ids=page_kit_tmpl_ids,
        page_kit_bom_map=page_kit_bom_map,
        page_blocking_by_so=service._batch_blocking_moves(so),
    )
    print(
        "direct formatter order: stock_status=%s packing_status=%s real_delivery_status=%s"
        % (
            direct_order.get("stock_status"),
            direct_order.get("packing_status"),
            direct_order.get("real_delivery_status"),
        )
    )
    for ldata in direct_order.get("lines") or []:
        pname = ldata.get("product_id")[1] if ldata.get("product_id") else ""
        eff_stock = qty(ldata.get("qty_warehouse_free")) + qty(ldata.get("qty_reserved_here"))
        print(
            "  direct line=%s kit=%s wh_free=%.2f reserved=%.2f eff_stock=%.2f"
            % (
                pname,
                ldata.get("is_kit"),
                qty(ldata.get("qty_warehouse_free")),
                qty(ldata.get("qty_reserved_here")),
                eff_stock,
            )
        )
except Exception as exc:
    print("Direct formatter check failed: %s" % exc)

line("DONE")
