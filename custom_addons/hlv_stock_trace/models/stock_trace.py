from datetime import datetime

import pytz

from odoo import api, models


class StockTrace(models.AbstractModel):
    """Backend logic for 'Theo dõi tồn kho theo thời gian'.

    Given a product and a start date, compute the on-hand quantity at that
    date vs now, and break the difference down into nhập kho / bán hàng /
    chuyển kho, at 3 levels of granularity:
      - toàn công ty (get_company_overview)
      - 1 kho cụ thể, kèm luân chuyển nội bộ (get_warehouse_detail)
      - 1 vị trí cụ thể, timeline chi tiết (get_location_timeline)

    Perf note: opening balances are derived arithmetically as
    (current on-hand from stock.quant) - (net moves in the period), using
    2-3 grouped queries total — never one qty_available(to_date=...) call
    per location. That historical-context call is expensive (it re-walks
    stock.move for every distinct call), so doing it once per location in a
    warehouse with many bin locations made the dashboard take up to a
    minute to load; this version scales with the number of DISTINCT
    warehouses/queries, not the number of locations.
    """
    _name = "stock.trace"
    _description = "Stock Trace"

    # ------------------------------------------------------------------
    # generic helpers
    # ------------------------------------------------------------------
    def _r(self, value):
        return round(float(value or 0.0), 2)

    def _rg_num(self, row, base):
        value = row.get(f"{base}_sum")
        if value is None:
            value = row.get(base)
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0

    def _date_bounds(self, date_from, date_to=None):
        """Return (date_from_str, date_to_str, date_to_display) in UTC,
        interpreting the input dates in the user's timezone (fallback VN)."""
        tz_name = self.env.user.tz or "Asia/Ho_Chi_Minh"
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.timezone("Asia/Ho_Chi_Minh")

        if not date_to:
            date_to_display = datetime.now(tz).strftime("%Y-%m-%d")
        else:
            date_to_display = date_to

        def local_to_utc_start(d_str):
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            return tz.localize(dt).astimezone(pytz.utc).replace(tzinfo=None)

        def local_to_utc_end(d_str):
            dt = datetime.strptime(d_str + " 23:59:59", "%Y-%m-%d %H:%M:%S")
            return tz.localize(dt).astimezone(pytz.utc).replace(tzinfo=None)

        date_from_str = local_to_utc_start(date_from).strftime("%Y-%m-%d %H:%M:%S")
        date_to_str = local_to_utc_end(date_to_display).strftime("%Y-%m-%d %H:%M:%S")
        return date_from_str, date_to_str, date_to_display

    def _utc_to_local_str(self, dt_utc, fmt="%d/%m/%Y %H:%M"):
        if not dt_utc:
            return ""
        tz_name = self.env.user.tz or "Asia/Ho_Chi_Minh"
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.timezone("Asia/Ho_Chi_Minh")
        dt = pytz.utc.localize(dt_utc.replace(tzinfo=None)).astimezone(tz)
        return dt.strftime(fmt)

    def _qty(self, move):
        return float(getattr(move, "quantity", 0) or getattr(move, "quantity_done", 0) or 0)

    def _warehouse_location_ids(self, warehouse):
        return self.env["stock.location"].search([
            ("id", "child_of", warehouse.view_location_id.id),
            ("usage", "in", ("internal", "transit")),
        ])

    # ---- bulk (grouped-query) balance helpers -------------------------
    def _quant_map(self, product_id, loc_ids):
        """location_id -> current on-hand qty. ONE grouped query."""
        if not loc_ids:
            return {}
        rows = self.env["stock.quant"].sudo().read_group(
            [("product_id", "=", product_id), ("location_id", "in", loc_ids)],
            ["location_id", "quantity:sum"], ["location_id"], lazy=False,
        )
        return {r["location_id"][0]: self._rg_num(r, "quantity") for r in rows if r.get("location_id")}

    def _period_moves(self, product_id, date_from_str, date_to_str, loc_ids=None):
        """All done moves for the product in the period. If loc_ids is given,
        restrict to moves touching at least one of those locations — still a
        SINGLE query regardless of how many locations are in loc_ids."""
        domain = [
            ("product_id", "=", product_id),
            ("state", "=", "done"),
            ("date", ">=", date_from_str),
            ("date", "<=", date_to_str),
        ]
        if loc_ids is not None:
            domain += ["|", ("location_id", "in", loc_ids), ("location_dest_id", "in", loc_ids)]
        return self.env["stock.move"].search(domain, order="date asc, id asc")

    def _net_flow_maps(self, moves):
        """One pass over an already-fetched moves recordset ->
        (qty_in_by_location, qty_out_by_location)."""
        qty_in, qty_out = {}, {}
        for move in moves:
            qty = self._qty(move)
            if qty <= 0:
                continue
            dest_id = move.location_dest_id.id
            src_id = move.location_id.id
            if dest_id == src_id:
                continue
            qty_in[dest_id] = qty_in.get(dest_id, 0.0) + qty
            qty_out[src_id] = qty_out.get(src_id, 0.0) + qty
        return qty_in, qty_out

    def _opening(self, loc_ids, quant_map, qty_in_map, qty_out_map):
        closing = sum(quant_map.get(l, 0.0) for l in loc_ids)
        moved_in = sum(qty_in_map.get(l, 0.0) for l in loc_ids)
        moved_out = sum(qty_out_map.get(l, 0.0) for l in loc_ids)
        return closing - moved_in + moved_out, closing

    # ---- flow classification (boundary-crossing, in-memory) ------------
    def _summarize_flow(self, moves, loc_set):
        """Classify moves crossing the boundary of loc_set into nhập/bán/chuyển,
        skipping moves that stay fully inside the set (pure internal circulation)."""
        received = sold = transfer_in = transfer_out = 0.0
        receipt_lines, sale_lines, transfer_pairs = [], [], {}

        for move in moves:
            is_dest = move.location_dest_id.id in loc_set
            is_src = move.location_id.id in loc_set
            if is_dest == is_src:
                continue  # both inside (internal) or both outside (unrelated)

            qty = self._qty(move)
            if qty <= 0:
                continue

            if is_dest:
                other = move.location_id
                if other.usage in ("supplier", "inventory", "production"):
                    received += qty
                    receipt_lines.append({
                        "from": other.display_name,
                        "to": move.location_dest_id.display_name,
                        "qty": self._r(qty),
                    })
                else:
                    transfer_in += qty
                    key = (other.display_name, move.location_dest_id.display_name)
                    transfer_pairs[key] = transfer_pairs.get(key, 0.0) + qty
            else:
                other = move.location_dest_id
                if other.usage == "customer":
                    sold += qty
                    sale_lines.append({
                        "from": move.location_id.display_name,
                        "to": other.display_name,
                        "qty": self._r(qty),
                    })
                elif other.usage in ("inventory", "production"):
                    pass  # điều chỉnh tồn kho — bỏ qua ở mức tổng hợp
                else:
                    transfer_out += qty
                    key = (move.location_id.display_name, other.display_name)
                    transfer_pairs[key] = transfer_pairs.get(key, 0.0) + qty

        return {
            "received": self._r(received),
            "sold": self._r(sold),
            "transfer_in": self._r(transfer_in),
            "transfer_out": self._r(transfer_out),
            "receipt_lines": receipt_lines,
            "sale_lines": sale_lines,
            "transfer_lines": [
                {"from": k[0], "to": k[1], "qty": self._r(v)}
                for k, v in transfer_pairs.items()
            ],
        }

    def _per_location_flow(self, moves, loc_ids):
        """One pass over an already-fetched moves recordset -> per-location
        {received, sold, transfer_in, transfer_out}, each location's own
        ledger (any move touching it counts, unlike the scope-boundary
        version above)."""
        result = {lid: {"received": 0.0, "sold": 0.0, "transfer_in": 0.0, "transfer_out": 0.0}
                   for lid in loc_ids}
        loc_set = set(loc_ids)
        for move in moves:
            qty = self._qty(move)
            if qty <= 0:
                continue
            dest, src = move.location_dest_id, move.location_id
            if dest.id == src.id:
                continue
            if dest.id in loc_set:
                bucket = result[dest.id]
                if src.usage in ("supplier", "inventory", "production"):
                    bucket["received"] += qty
                else:
                    bucket["transfer_in"] += qty
            if src.id in loc_set:
                bucket = result[src.id]
                if dest.usage == "customer":
                    bucket["sold"] += qty
                elif dest.usage in ("inventory", "production"):
                    pass
                else:
                    bucket["transfer_out"] += qty
        return result

    # ------------------------------------------------------------------
    # level 1: toàn công ty
    # ------------------------------------------------------------------
    @api.model
    def get_company_overview(self, product_id, date_from, date_to=None):
        product = self.env["product.product"].browse(product_id)
        warehouses = self.env["stock.warehouse"].search([])
        date_from_str, date_to_str, date_to_display = self._date_bounds(date_from, date_to)

        wh_loc_ids, wh_loc_map, known_loc_ids = {}, {}, set()
        for wh in warehouses:
            locs = self._warehouse_location_ids(wh)
            wh_loc_ids[wh.id] = locs.ids
            for loc in locs:
                wh_loc_map[loc.id] = wh
            known_loc_ids |= set(locs.ids)

        # One unrestricted move search for the whole period — used both to
        # discover "extra" locations (e.g. a shared transit point outside
        # any warehouse tree) and to derive every flow number below.
        period_moves = self._period_moves(product_id, date_from_str, date_to_str)

        extra_loc_ids = set()
        for move in period_moves:
            for loc in (move.location_id, move.location_dest_id):
                if loc.usage in ("internal", "transit") and loc.id not in known_loc_ids:
                    extra_loc_ids.add(loc.id)
        # also include locations currently holding stock, in case they had
        # no movement in the chosen period but still count toward "hiện tại"
        quants_here = self.env["stock.quant"].sudo().search([
            ("product_id", "=", product_id),
            ("location_id.usage", "in", ("internal", "transit")),
            ("quantity", "!=", 0),
        ])
        extra_loc_ids |= (set(quants_here.location_id.ids) - known_loc_ids)

        all_loc_ids = list(known_loc_ids | extra_loc_ids)
        all_loc_set = set(all_loc_ids)

        quant_map = self._quant_map(product_id, all_loc_ids)
        qty_in_map, qty_out_map = self._net_flow_maps(period_moves)
        per_loc_flow = self._per_location_flow(period_moves, all_loc_ids)

        opening, closing = self._opening(all_loc_ids, quant_map, qty_in_map, qty_out_map)
        flow = self._summarize_flow(period_moves, all_loc_set)

        warehouse_rows = []
        for wh in warehouses:
            loc_ids = wh_loc_ids.get(wh.id) or []
            if not loc_ids:
                continue
            w_opening, w_closing = self._opening(loc_ids, quant_map, qty_in_map, qty_out_map)
            if self._r(w_opening) == 0 and self._r(w_closing) == 0:
                continue
            w_flow = self._summarize_flow(period_moves, set(loc_ids))
            warehouse_rows.append({
                "warehouse_id": wh.id,
                "warehouse_name": wh.name,
                "location_count": len(loc_ids),
                "opening": self._r(w_opening),
                "closing": self._r(w_closing),
                "received": w_flow["received"],
                "sold": w_flow["sold"],
                "transfer_in": w_flow["transfer_in"],
                "transfer_out": w_flow["transfer_out"],
            })

        if extra_loc_ids:
            t_ids = list(extra_loc_ids)
            t_opening, t_closing = self._opening(t_ids, quant_map, qty_in_map, qty_out_map)
            if self._r(t_opening) or self._r(t_closing):
                warehouse_rows.append({
                    "warehouse_id": False,
                    "warehouse_name": "Đang chuyển giữa các kho / khác",
                    "location_count": len(t_ids),
                    "opening": self._r(t_opening),
                    "closing": self._r(t_closing),
                    "received": 0.0, "sold": 0.0, "transfer_in": 0.0, "transfer_out": 0.0,
                })

        location_rows = []
        for loc_id in all_loc_ids:
            l_opening, l_closing = self._opening([loc_id], quant_map, qty_in_map, qty_out_map)
            l_flow = per_loc_flow.get(loc_id, {})
            if (self._r(l_opening) == 0 and self._r(l_closing) == 0
                    and not any(l_flow.values())):
                continue
            loc = self.env["stock.location"].browse(loc_id)
            wh = wh_loc_map.get(loc_id)
            location_rows.append({
                "location_id": loc_id,
                "location_name": loc.display_name,
                "warehouse_name": wh.name if wh else "—",
                "opening": self._r(l_opening),
                "closing": self._r(l_closing),
                "received": self._r(l_flow.get("received")),
                "sold": self._r(l_flow.get("sold")),
                "transfer_in": self._r(l_flow.get("transfer_in")),
                "transfer_out": self._r(l_flow.get("transfer_out")),
            })
        location_rows.sort(key=lambda r: (r["warehouse_name"], r["location_name"]))
        warehouse_rows.sort(key=lambda r: r["warehouse_name"])

        return {
            "product_id": product.id,
            "product_name": product.display_name,
            "date_from": date_from,
            "date_to": date_to_display,
            "opening": self._r(opening),
            "closing": self._r(closing),
            "flow": flow,
            "warehouses": warehouse_rows,
            "locations": location_rows,
        }

    # ------------------------------------------------------------------
    # level 2: 1 kho cụ thể
    # ------------------------------------------------------------------
    @api.model
    def get_warehouse_detail(self, product_id, date_from, warehouse_id, date_to=None):
        product = self.env["product.product"].browse(product_id)
        warehouse = self.env["stock.warehouse"].browse(warehouse_id)
        date_from_str, date_to_str, date_to_display = self._date_bounds(date_from, date_to)

        locs = self._warehouse_location_ids(warehouse)
        loc_ids = locs.ids

        moves = self._period_moves(product_id, date_from_str, date_to_str, loc_ids=loc_ids)

        quant_map = self._quant_map(product_id, loc_ids)
        qty_in_map, qty_out_map = self._net_flow_maps(moves)
        per_loc_flow = self._per_location_flow(moves, loc_ids)

        opening, closing = self._opening(loc_ids, quant_map, qty_in_map, qty_out_map)
        boundary_flow = self._summarize_flow(moves, set(loc_ids))

        throughput = {}
        loc_id_set = set(loc_ids)
        for move in moves:
            if move.location_id.id not in loc_id_set or move.location_dest_id.id not in loc_id_set:
                continue
            if move.location_id.id == move.location_dest_id.id:
                continue
            qty = self._qty(move)
            if qty <= 0:
                continue
            throughput.setdefault(move.location_id.id, {"in": 0.0, "out": 0.0})
            throughput.setdefault(move.location_dest_id.id, {"in": 0.0, "out": 0.0})
            throughput[move.location_id.id]["out"] += qty
            throughput[move.location_dest_id.id]["in"] += qty

        internal_throughput = [
            {
                "location_id": lid,
                "location_name": self.env["stock.location"].browse(lid).display_name,
                "in": self._r(v["in"]),
                "out": self._r(v["out"]),
            }
            for lid, v in throughput.items()
        ]
        internal_throughput.sort(key=lambda r: r["location_name"])

        location_rows = []
        for loc in locs:
            l_opening, l_closing = self._opening([loc.id], quant_map, qty_in_map, qty_out_map)
            l_flow = per_loc_flow.get(loc.id, {})
            l_through = throughput.get(loc.id, {"in": 0.0, "out": 0.0})
            if (self._r(l_opening) == 0 and self._r(l_closing) == 0
                    and not any(l_flow.values()) and not l_through["in"] and not l_through["out"]):
                continue
            location_rows.append({
                "location_id": loc.id,
                "location_name": loc.display_name,
                "opening": self._r(l_opening),
                "closing": self._r(l_closing),
                "received": self._r(l_flow.get("received")),
                "sold": self._r(l_flow.get("sold")),
                "transfer_in": self._r(l_flow.get("transfer_in")),
                "transfer_out": self._r(l_flow.get("transfer_out")),
                "internal_in": self._r(l_through["in"]),
                "internal_out": self._r(l_through["out"]),
            })
        location_rows.sort(key=lambda r: r["location_name"])

        return {
            "product_id": product.id,
            "product_name": product.display_name,
            "warehouse_id": warehouse.id,
            "warehouse_name": warehouse.name,
            "date_from": date_from,
            "date_to": date_to_display,
            "opening": self._r(opening),
            "closing": self._r(closing),
            "boundary_flow": boundary_flow,
            "internal_throughput": internal_throughput,
            "locations": location_rows,
        }

    # ------------------------------------------------------------------
    # level 3: 1 vị trí cụ thể
    # ------------------------------------------------------------------
    @api.model
    def get_location_timeline(self, product_id, date_from, location_id, date_to=None):
        product = self.env["product.product"].browse(product_id)
        location = self.env["stock.location"].browse(location_id)
        date_from_str, date_to_str, date_to_display = self._date_bounds(date_from, date_to)

        moves = self._period_moves(product_id, date_from_str, date_to_str, loc_ids=[location_id])
        quant_map = self._quant_map(product_id, [location_id])
        qty_in_map, qty_out_map = self._net_flow_maps(moves)
        opening, _closing = self._opening([location_id], quant_map, qty_in_map, qty_out_map)

        loc_set = {location_id}
        running = opening
        lines = [{
            "type": "opening",
            "title": "Tồn đầu kỳ",
            "date": date_from,
            "reference": "",
            "other_location": "",
            "partner_name": "",
            "qty": None,
            "uom": "",
            "balance": self._r(running),
        }]

        for move in moves:
            is_dest = move.location_dest_id.id in loc_set
            is_src = move.location_id.id in loc_set
            if is_dest == is_src:
                continue

            qty = self._qty(move)
            if qty <= 0:
                continue

            other = move.location_id if is_dest else move.location_dest_id
            picking = move.picking_id
            partner = picking.partner_id if picking else False

            if is_dest:
                running += qty
                signed_qty = qty
                if other.usage in ("supplier", "inventory", "production"):
                    mtype, title = "receipt", "Nhập kho"
                else:
                    mtype, title = "transfer_in", "Chuyển kho đến"
            else:
                running -= qty
                signed_qty = -qty
                if other.usage == "customer":
                    mtype, title = "sale", "Bán hàng"
                elif other.usage in ("inventory", "production"):
                    mtype, title = "adjustment", "Điều chỉnh tồn kho"
                else:
                    mtype, title = "transfer_out", "Chuyển kho đi"

            lines.append({
                "type": mtype,
                "title": title,
                "date": self._utc_to_local_str(move.date),
                "reference": (picking.name if picking else move.name) or "",
                "other_location": other.display_name,
                "partner_name": partner.name if partner else "",
                "qty": self._r(signed_qty),
                "uom": move.product_uom.name or "",
                "balance": self._r(running),
            })

        lines.append({
            "type": "current",
            "title": "Hiện tại",
            "date": date_to_display,
            "reference": "",
            "other_location": "",
            "partner_name": "",
            "qty": None,
            "uom": "",
            "balance": self._r(running),
        })

        return {
            "product_id": product.id,
            "product_name": product.display_name,
            "location_id": location.id,
            "location_name": location.display_name,
            "date_from": date_from,
            "date_to": date_to_display,
            "lines": lines,
        }
