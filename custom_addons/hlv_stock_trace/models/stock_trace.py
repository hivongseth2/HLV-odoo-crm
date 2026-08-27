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
    a handful of grouped queries total — never one qty_available(to_date=...)
    call per location (that is expensive: it re-walks stock.move on every
    distinct call, which made the dashboard take up to a minute to load on
    a warehouse with many bin locations). This version scales with the
    number of distinct warehouses/queries, not the number of locations.

    A location's "tồn đầu kỳ" can come out negative — that is not a bug,
    it is the arithmetic reconstruction of a real Odoo state: a staging /
    transit location can be reserved-out before it is physically restocked
    (backorders, automated putaway). Every method below exposes
    `negative_opening` on the row so the UI can flag it instead of hiding
    it or making it look like broken data.
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
        """Classify moves crossing the boundary of loc_set into nhập/bán/chuyển/
        điều chỉnh kiểm kho, skipping moves that stay fully inside the set
        (pure internal circulation). Inventory adjustments (usage='inventory',
        e.g. from "Cập nhật số lượng"/kiểm kho) and manufacturing moves
        (usage='production') are their OWN category — they must never be
        silently folded into "received" or silently dropped, since that is
        exactly what makes an opening-balance swing look unexplained."""
        received = sold = transfer_in = transfer_out = adjustment = 0.0
        receipt_lines, sale_lines, transfer_pairs = [], [], {}
        adjustment_lines = []

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
                if other.usage == "supplier":
                    received += qty
                    receipt_lines.append({
                        "from": other.display_name,
                        "to": move.location_dest_id.display_name,
                        "qty": self._r(qty),
                    })
                elif other.usage in ("inventory", "production"):
                    adjustment += qty
                    adjustment_lines.append({
                        "location": move.location_dest_id.display_name,
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
                    adjustment -= qty
                    adjustment_lines.append({
                        "location": move.location_id.display_name,
                        "qty": self._r(-qty),
                    })
                else:
                    transfer_out += qty
                    key = (move.location_id.display_name, other.display_name)
                    transfer_pairs[key] = transfer_pairs.get(key, 0.0) + qty

        return {
            "received": self._r(received),
            "sold": self._r(sold),
            "transfer_in": self._r(transfer_in),
            "transfer_out": self._r(transfer_out),
            "adjustment": self._r(adjustment),
            "adjustment_lines": adjustment_lines,
            "receipt_lines": receipt_lines,
            "sale_lines": sale_lines,
            "transfer_lines": [
                {"from": k[0], "to": k[1], "qty": self._r(v)}
                for k, v in transfer_pairs.items()
            ],
        }

    def _per_location_flow(self, moves, loc_ids):
        """One pass over an already-fetched moves recordset -> per-location
        {received, sold, transfer_in, transfer_out, adjustment}, each
        location's own ledger (any move touching it counts, unlike the
        scope-boundary version above). transfer_in/out here means "to/from
        another internal or transit location that is NOT itself in loc_ids"
        — i.e. it already excludes moves that are purely internal to the
        set passed in (those are reported separately as throughput, see
        get_warehouse_detail). adjustment is SIGNED (positive = found extra
        stock via kiểm kho, negative = written off) — inventory-adjustment
        and production moves are never folded into received/transfer_out,
        that mislabels them and used to make opening-balance swings look
        unexplained."""
        result = {lid: {"received": 0.0, "sold": 0.0, "transfer_in": 0.0, "transfer_out": 0.0,
                         "adjustment": 0.0}
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
                if src.usage == "supplier":
                    bucket["received"] += qty
                elif src.usage in ("inventory", "production"):
                    bucket["adjustment"] += qty
                else:
                    bucket["transfer_in"] += qty
            if src.id in loc_set:
                bucket = result[src.id]
                if dest.usage == "customer":
                    bucket["sold"] += qty
                elif dest.usage in ("inventory", "production"):
                    bucket["adjustment"] -= qty
                else:
                    bucket["transfer_out"] += qty
        return result

    def _location_row(self, loc, opening, closing, received, sold, transfer_in, transfer_out,
                       adjustment=0.0, extra=None):
        adj = adjustment or 0.0
        row = {
            "location_id": loc.id,
            "location_name": loc.display_name,
            "opening": self._r(opening),
            "closing": self._r(closing),
            "received": self._r(received),
            "sold": self._r(sold),
            "transfer_in": self._r(transfer_in),
            "transfer_out": self._r(transfer_out),
            "adjustment": self._r(adj),
            "inflow": self._r((received or 0) + (transfer_in or 0) + max(adj, 0.0)),
            "outflow": self._r((sold or 0) + (transfer_out or 0) + max(-adj, 0.0)),
            "negative_opening": self._r(opening) < 0,
        }
        if extra:
            row.update(extra)
            row["inflow"] = self._r(row["inflow"] + (extra.get("internal_in") or 0))
            row["outflow"] = self._r(row["outflow"] + (extra.get("internal_out") or 0))
        return row

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
                "adjustment": w_flow["adjustment"],
                "negative_opening": self._r(w_opening) < 0,
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
                    "adjustment": 0.0,
                    "negative_opening": self._r(t_opening) < 0,
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
            row = self._location_row(
                loc, l_opening, l_closing,
                l_flow.get("received"), l_flow.get("sold"),
                l_flow.get("transfer_in"), l_flow.get("transfer_out"),
                adjustment=l_flow.get("adjustment"),
            )
            row["warehouse_name"] = wh.name if wh else "—"
            location_rows.append(row)
        location_rows.sort(key=lambda r: (r["warehouse_name"], r["location_name"]))
        warehouse_rows.sort(key=lambda r: r["warehouse_name"])

        return {
            "product_id": product.id,
            "product_name": product.display_name,
            "date_from": date_from,
            "date_to": date_to_display,
            "opening": self._r(opening),
            "closing": self._r(closing),
            "negative_opening": self._r(opening) < 0,
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
        loc_id_set = set(loc_ids)

        moves = self._period_moves(product_id, date_from_str, date_to_str, loc_ids=loc_ids)

        quant_map = self._quant_map(product_id, loc_ids)
        qty_in_map, qty_out_map = self._net_flow_maps(moves)
        per_loc_flow = self._per_location_flow(moves, loc_ids)

        opening, closing = self._opening(loc_ids, quant_map, qty_in_map, qty_out_map)
        boundary_flow = self._summarize_flow(moves, loc_id_set)

        throughput = {}
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
            row = self._location_row(
                loc, l_opening, l_closing,
                l_flow.get("received"), l_flow.get("sold"),
                l_flow.get("transfer_in"), l_flow.get("transfer_out"),
                adjustment=l_flow.get("adjustment"),
                extra={"internal_in": self._r(l_through["in"]), "internal_out": self._r(l_through["out"])},
            )
            location_rows.append(row)
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
            "negative_opening": self._r(opening) < 0,
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
                if other.usage == "supplier":
                    mtype, title = "receipt", "Nhập kho"
                elif other.usage in ("inventory", "production"):
                    mtype, title = "adjustment", "Điều chỉnh tồn kho (kiểm kho)"
                else:
                    mtype, title = "transfer_in", "Chuyển kho đến"
            else:
                running -= qty
                signed_qty = -qty
                if other.usage == "customer":
                    mtype, title = "sale", "Bán hàng"
                elif other.usage in ("inventory", "production"):
                    mtype, title = "adjustment", "Điều chỉnh tồn kho (kiểm kho)"
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
            "opening_negative": self._r(opening) < 0,
            "lines": lines,
        }

    # ------------------------------------------------------------------
    # "Theo ngày" — daily ledger (any scope: company / warehouse / location)
    # ------------------------------------------------------------------
    def _resolve_scope(self, product_id, scope_type, scope_id, date_from_str, date_to_str):
        """Return (loc_ids, wh_of, period_moves) for the given scope.
        wh_of is a callable location_id -> warehouse_id (or None), only
        meaningful/needed for scope_type == 'company' (to tell an
        intra-warehouse move apart from an inter-warehouse one); it is
        None for 'warehouse'/'location' scope, where "chuyển kho" simply
        means "crosses the scope's own boundary". period_moves is None for
        'warehouse'/'location' (the caller fetches a loc_ids-restricted set
        itself); for 'company' it is the unrestricted move search this
        method already had to run to discover extra/transit locations —
        virtually every move for this product touches at least one of the
        resolved company loc_ids, so callers can reuse it as-is instead of
        re-querying (that used to be 2 full move scans per company-scope
        call)."""
        if scope_type == "location":
            return [scope_id], None, None
        if scope_type == "warehouse":
            return self._warehouse_location_ids(self.env["stock.warehouse"].browse(scope_id)).ids, None, None

        warehouses = self.env["stock.warehouse"].search([])
        wh_loc_map, known_loc_ids = {}, set()
        for wh in warehouses:
            for loc_id in self._warehouse_location_ids(wh).ids:
                wh_loc_map[loc_id] = wh.id
                known_loc_ids.add(loc_id)

        period_moves = self._period_moves(product_id, date_from_str, date_to_str)
        extra_loc_ids = set()
        for move in period_moves:
            for loc in (move.location_id, move.location_dest_id):
                if loc.usage in ("internal", "transit") and loc.id not in known_loc_ids:
                    extra_loc_ids.add(loc.id)
        quants_here = self.env["stock.quant"].sudo().search([
            ("product_id", "=", product_id),
            ("location_id.usage", "in", ("internal", "transit")),
            ("quantity", "!=", 0),
        ])
        extra_loc_ids |= (set(quants_here.location_id.ids) - known_loc_ids)

        return list(known_loc_ids | extra_loc_ids), wh_loc_map.get, period_moves

    def _classify_flow(self, move, loc_id_set, wh_of=None):
        """Classify one move against a scope into 0-2 (category, qty)
        contributions. category in {'mua','ban','chuyen_vao','chuyen_ra',
        'dieu_chinh'}. 'dieu_chinh' carries a SIGNED qty (positive = found
        extra stock via kiểm kho, negative = written off) — every other
        category carries a plain magnitude, sign is implied by the category.
        - dest in scope, src outside: 'mua' from a real supplier; 'dieu_chinh'
          (+) when src is the inventory-adjustment or production location
          (never folded into 'mua' — that hides why a balance moved); else
          'chuyen_vao' (arriving from elsewhere not itself counted, e.g.
          warehouse scope).
        - src in scope, dest outside: 'ban' to a real customer; 'dieu_chinh'
          (−) for inventory-adjustment/production; else 'chuyen_ra'.
        - both in scope: only relevant for company scope. A 2-step transfer
          (source warehouse -> shared transit location -> destination
          warehouse) is TWO stock.move records for ONE logical shipment —
          each leg touches the shared transit location, which belongs to NO
          warehouse (wh_of returns None for it). Naively comparing
          wh_of(src) != wh_of(dest) on EACH leg double-counts: the first leg
          (warehouse -> transit, None != warehouse_id) and the second leg
          (transit -> warehouse, warehouse_id != None) would each register
          as a full "crossed a warehouse boundary" event, turning one
          10-unit transfer into 20. Only emit the side that is actually a
          REAL warehouse: leaving a real warehouse is one 'chuyen_ra', later
          arriving at a real warehouse is one 'chuyen_vao' — a transit hop
          in between contributes neither on its own. A DIRECT move between
          two different real warehouses (no transit leg) still emits both,
          since that single move genuinely is the whole transfer. Same
          warehouse (or both ends untracked/transit) contributes nothing —
          that is pure intra-warehouse circulation (see internal_throughput
          on get_warehouse_detail for that)."""
        qty = self._qty(move)
        if qty <= 0:
            return []
        dest_id, src_id = move.location_dest_id.id, move.location_id.id
        is_dest = dest_id in loc_id_set
        is_src = src_id in loc_id_set

        if is_dest and not is_src:
            other = move.location_id
            if other.usage == "supplier":
                return [("mua", qty)]
            if other.usage in ("inventory", "production"):
                return [("dieu_chinh", qty)]
            return [("chuyen_vao", qty)]
        if is_src and not is_dest:
            other = move.location_dest_id
            if other.usage == "customer":
                return [("ban", qty)]
            if other.usage in ("inventory", "production"):
                return [("dieu_chinh", -qty)]
            return [("chuyen_ra", qty)]
        if is_dest and is_src and wh_of is not None:
            src_wh, dest_wh = wh_of(src_id), wh_of(dest_id)
            if src_wh == dest_wh:
                return []
            contribs = []
            if src_wh is not None:
                contribs.append(("chuyen_ra", qty))
            if dest_wh is not None:
                contribs.append(("chuyen_vao", qty))
            return contribs
        return []

    def _true_net(self, move, loc_id_set):
        """The move's ACTUAL effect on the scope's total on-hand — +qty if
        stock enters the scope from outside, -qty if it leaves, 0 if both
        ends are inside the scope (conservation: what left one location in
        the set arrived at another location in the same set, so the sum is
        unchanged) or both outside. This is deliberately independent of
        _classify_flow's category split: chuyen_vao/chuyen_ra exist to show
        warehouse-level activity and, for a 2-step transfer through a
        shared transit location, do NOT individually net to the true
        company-wide change (see _classify_flow's docstring) — only this
        function is safe to accumulate into a running balance."""
        qty = self._qty(move)
        if qty <= 0:
            return 0.0
        is_dest = move.location_dest_id.id in loc_id_set
        is_src = move.location_id.id in loc_id_set
        if is_dest and not is_src:
            return qty
        if is_src and not is_dest:
            return -qty
        return 0.0

    def _day_key(self, dt_utc):
        tz_name = self.env.user.tz or "Asia/Ho_Chi_Minh"
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.timezone("Asia/Ho_Chi_Minh")
        dt = pytz.utc.localize(dt_utc.replace(tzinfo=None)).astimezone(tz)
        return dt.strftime("%Y-%m-%d")

    @api.model
    def get_daily_ledger(self, product_id, date_from, scope_type, scope_id=None, date_to=None):
        date_from_str, date_to_str, date_to_display = self._date_bounds(date_from, date_to)
        loc_ids, wh_of, pre_moves = self._resolve_scope(product_id, scope_type, scope_id, date_from_str, date_to_str)
        loc_id_set = set(loc_ids)

        moves = pre_moves if pre_moves is not None else self._period_moves(
            product_id, date_from_str, date_to_str, loc_ids=loc_ids)
        quant_map = self._quant_map(product_id, loc_ids)
        qty_in_map, qty_out_map = self._net_flow_maps(moves)
        opening, closing = self._opening(loc_ids, quant_map, qty_in_map, qty_out_map)

        days = {}
        for move in moves:
            contribs = self._classify_flow(move, loc_id_set, wh_of=wh_of)
            true_net = self._true_net(move, loc_id_set)
            if not contribs and true_net == 0:
                continue
            d = self._day_key(move.date)
            bucket = days.setdefault(d, {
                "mua": 0.0, "ban": 0.0, "chuyen_vao": 0.0, "chuyen_ra": 0.0,
                "dieu_chinh": 0.0, "true_net": 0.0, "refs": set(),
            })
            for cat, qty in contribs:
                bucket[cat] += qty
            bucket["true_net"] += true_net
            ref = (move.picking_id.name if move.picking_id else move.name) or ""
            if ref:
                bucket["refs"].add(ref)

        running = opening
        day_rows = []
        for d in sorted(days.keys()):
            b = days[d]
            # "Biến động"/"Tồn cuối ngày" MUST use true_net, not the
            # mua/ban/chuyen_vao/chuyen_ra columns — those can legitimately
            # not sum to the real change on a day that only sees one leg of
            # a multi-day transit transfer (see _true_net's docstring).
            net = b["true_net"]
            running += net
            day_rows.append({
                "date": d,
                "mua": self._r(b["mua"]),
                "ban": self._r(b["ban"]),
                "chuyen_vao": self._r(b["chuyen_vao"]),
                "chuyen_ra": self._r(b["chuyen_ra"]),
                "dieu_chinh": self._r(b["dieu_chinh"]),
                "net": self._r(net),
                "balance": self._r(running),
                "ref_count": len(b["refs"]),
            })
        day_rows.reverse()  # most recent first, matching the ledger UI

        return {
            "product_id": product_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "date_from": date_from,
            "date_to": date_to_display,
            "opening": self._r(opening),
            "closing": self._r(closing),
            "days": day_rows,
        }

    def _wh_name_map(self, wh_ids):
        wh_ids = [w for w in set(wh_ids) if w]
        if not wh_ids:
            return {}
        return {w.id: w.name for w in self.env["stock.warehouse"].browse(wh_ids)}

    def _merge_transit_legs(self, moves):
        """Merge the two stock.move legs of a 2-step transfer (source
        warehouse -> shared transit location -> destination warehouse) into
        ONE display entry, so the UI shows the real origin -> real
        destination instead of two separate rows through a transit stop.
        Legs are linked via Odoo's own move_dest_ids/move_orig_ids (the
        chain a push/pull route rule sets up) — matched only when the
        continuation is in the SAME `moves` recordset (e.g. same day, for
        get_day_detail) and genuinely departs from where the first leg
        arrived. Returns one dict per move NOT itself a consumed
        continuation: {move, from_loc, to_loc, via_transit, extra_ref,
        arrival_time}."""
        move_ids = {m.id for m in moves}
        by_id = {m.id: m for m in moves}
        consumed = set()
        result = []
        for m in moves:
            if m.id in consumed:
                continue
            continuation = None
            if m.location_dest_id.usage == "transit":
                for dest in m.move_dest_ids:
                    if dest.id in move_ids and dest.location_id.id == m.location_dest_id.id:
                        continuation = by_id[dest.id]
                        break
            if continuation is not None:
                consumed.add(continuation.id)
                result.append({
                    "move": m,
                    "from_loc": m.location_id,
                    "to_loc": continuation.location_dest_id,
                    "via_transit": m.location_dest_id.display_name,
                    "extra_ref": (continuation.picking_id.name if continuation.picking_id else continuation.name) or "",
                    "arrival_time": self._utc_to_local_str(continuation.date, fmt="%H:%M"),
                })
            else:
                result.append({
                    "move": m,
                    "from_loc": m.location_id,
                    "to_loc": m.location_dest_id,
                    "via_transit": "",
                    "extra_ref": "",
                    "arrival_time": "",
                })
        return result

    @api.model
    def get_day_detail(self, product_id, day_date, scope_type, scope_id=None):
        """Detail for ONE day (local date 'YYYY-MM-DD'), for expanding a row
        in the daily ledger: one row per move that day (với Từ/Đến rõ ràng,
        không gộp theo vị trí — dễ đối chiếu với phiếu), and — for
        company/warehouse scope — an end-of-day snapshot per location."""
        date_from_str, date_to_str, _ = self._date_bounds(day_date, day_date)
        loc_ids, wh_of, pre_moves = self._resolve_scope(product_id, scope_type, scope_id, date_from_str, date_to_str)
        loc_id_set = set(loc_ids)

        day_moves = pre_moves if pre_moves is not None else self._period_moves(
            product_id, date_from_str, date_to_str, loc_ids=loc_ids)

        wh_names = self._wh_name_map(
            [wh_of(l) for l in loc_ids] if wh_of else []
        )

        transactions = []
        for leg in self._merge_transit_legs(day_moves):
            move = leg["move"]
            contribs = self._classify_flow(move, loc_id_set, wh_of=wh_of)
            if not contribs:
                continue
            # one row per MOVE (not per contribution) — Từ/Đến already show
            # direction, so an inter-warehouse move (2 contribs, symmetric,
            # or a merged transit-hop leg) only needs one line.
            category = "chuyen_kho" if (len(contribs) == 2 or leg["via_transit"]) else contribs[0][0]
            qty = self._qty(move)
            picking = move.picking_id
            partner = picking.partner_id if picking else False
            from_loc, to_loc = leg["from_loc"], leg["to_loc"]
            from_wh_id = wh_of(from_loc.id) if wh_of else None
            to_wh_id = wh_of(to_loc.id) if wh_of else None
            reference = (picking.name if picking else move.name) or ""
            if leg["extra_ref"]:
                reference = f"{reference} → {leg['extra_ref']}"
            transactions.append({
                "category": category,
                "from_location": from_loc.display_name,
                "from_warehouse": wh_names.get(from_wh_id, ""),
                "to_location": to_loc.display_name,
                "to_warehouse": wh_names.get(to_wh_id, ""),
                "via_transit": leg["via_transit"],
                "time": self._utc_to_local_str(move.date, fmt="%H:%M"),
                "arrival_time": leg["arrival_time"],
                "reference": reference,
                "partner_name": partner.name if partner else "",
                "qty": self._r(qty),
            })
        transactions.sort(key=lambda t: t["time"])

        locations_snapshot = []
        if scope_type in ("company", "warehouse") and loc_ids:
            quant_map = self._quant_map(product_id, loc_ids)
            now_utc_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            after_moves = self._period_moves(product_id, date_to_str, now_utc_str, loc_ids=loc_ids)
            qty_in_after, qty_out_after = self._net_flow_maps(after_moves)
            total = 0.0
            for loc_id in loc_ids:
                bal = (quant_map.get(loc_id, 0.0)
                       - qty_in_after.get(loc_id, 0.0) + qty_out_after.get(loc_id, 0.0))
                bal = self._r(bal)
                total += bal
                if bal == 0:
                    # skip empty bins entirely — a warehouse tree can have
                    # hundreds of shelf/bin locations (THUNG 1, THUNG 2, ...)
                    # that never held this product; rendering all of them as
                    # "0 Cái" rows is exactly what made this panel feel slow.
                    # Still counted in `total` above, just not displayed.
                    continue
                loc = self.env["stock.location"].browse(loc_id)
                wh_id = wh_of(loc_id) if wh_of else None
                locations_snapshot.append({
                    "location_id": loc_id,
                    "location_name": loc.display_name,
                    "warehouse_name": wh_names.get(wh_id, "—"),
                    "balance": bal,
                })
            locations_snapshot.sort(key=lambda r: (r["warehouse_name"], r["location_name"]))
            locations_snapshot.append({
                "location_id": False,
                "location_name": "Tổng",
                "warehouse_name": "",
                "balance": self._r(total),
                "is_total": True,
            })

        return {
            "date": day_date,
            "transactions": transactions,
            "locations_snapshot": locations_snapshot,
        }

    # ------------------------------------------------------------------
    # "Timeline" — flat chronological view (any scope), one card per move
    # ------------------------------------------------------------------
    @api.model
    def get_full_timeline(self, product_id, date_from, scope_type, scope_id=None, date_to=None):
        product = self.env["product.product"].browse(product_id)
        date_from_str, date_to_str, date_to_display = self._date_bounds(date_from, date_to)
        loc_ids, wh_of, pre_moves = self._resolve_scope(product_id, scope_type, scope_id, date_from_str, date_to_str)
        loc_id_set = set(loc_ids)

        moves = pre_moves if pre_moves is not None else self._period_moves(
            product_id, date_from_str, date_to_str, loc_ids=loc_ids)
        quant_map = self._quant_map(product_id, loc_ids)
        qty_in_map, qty_out_map = self._net_flow_maps(moves)
        opening, closing = self._opening(loc_ids, quant_map, qty_in_map, qty_out_map)

        wh_names = self._wh_name_map([wh_of(l) for l in loc_ids] if wh_of else [])

        running = opening
        lines = [{
            "type": "opening",
            "date": date_from,
            "from_location": "", "from_warehouse": "",
            "to_location": "", "to_warehouse": "",
            "reference": "", "partner_name": "",
            "qty": None,
            "balance": self._r(running),
        }]

        for leg in self._merge_transit_legs(moves):
            move = leg["move"]
            contribs = self._classify_flow(move, loc_id_set, wh_of=wh_of)
            # running balance uses the TRUE effect on the scope's total —
            # never the display categories (see _true_net's docstring: a
            # transit-hop leg's chuyen_ra/chuyen_vao must NOT move the
            # balance, the stock is still inside the scope in transit).
            running += self._true_net(move, loc_id_set)
            if not contribs:
                continue

            merged = bool(leg["via_transit"])
            category = "chuyen_kho" if (len(contribs) == 2 or merged) else contribs[0][0]
            if len(contribs) == 2 or merged:
                display_qty = self._qty(move)  # lateral move, show plain magnitude
            else:
                cat0, qty0 = contribs[0]
                display_qty = qty0 if cat0 in ("mua", "chuyen_vao", "dieu_chinh") else -qty0

            picking = move.picking_id
            partner = picking.partner_id if picking else False
            from_loc, to_loc = leg["from_loc"], leg["to_loc"]
            reference = (picking.name if picking else move.name) or ""
            if leg["extra_ref"]:
                reference = f"{reference} → {leg['extra_ref']}"
            lines.append({
                "type": category,
                "date": self._utc_to_local_str(move.date),
                "from_location": from_loc.display_name,
                "from_warehouse": wh_names.get(wh_of(from_loc.id), "") if wh_of else "",
                "to_location": to_loc.display_name,
                "to_warehouse": wh_names.get(wh_of(to_loc.id), "") if wh_of else "",
                "via_transit": leg["via_transit"],
                "reference": reference,
                "partner_name": partner.name if partner else "",
                "qty": self._r(display_qty),
                "balance": self._r(running),
            })

        lines.append({
            "type": "current",
            "date": date_to_display,
            "from_location": "", "from_warehouse": "",
            "to_location": "", "to_warehouse": "",
            "reference": "", "partner_name": "",
            "qty": None,
            "balance": self._r(running),
        })

        return {
            "product_id": product.id,
            "product_name": product.display_name,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "date_from": date_from,
            "date_to": date_to_display,
            "opening": self._r(opening),
            "closing": self._r(closing),
            "lines": lines,
        }

    @api.model
    def get_scope_options(self, product_id):
        """Populate the 'Chọn 1 kho...' / 'Chọn 1 vị trí...' pickers with
        every warehouse, and every location (internal/transit) that
        currently holds this product plus every warehouse's own location
        tree. Deliberately does NOT scan the product's whole move history
        (that used to be an unbounded stock.move search — expensive, and
        the main cause of a slow first load) — a location that is neither
        a live warehouse location nor currently holding stock isn't a
        useful trace target anyway."""
        warehouses = self.env["stock.warehouse"].search([])
        wh_loc_map, known_loc_ids = {}, set()
        for wh in warehouses:
            for loc_id in self._warehouse_location_ids(wh).ids:
                wh_loc_map[loc_id] = wh
                known_loc_ids.add(loc_id)

        quants_here = self.env["stock.quant"].sudo().search([
            ("product_id", "=", product_id),
            ("location_id.usage", "in", ("internal", "transit")),
            ("quantity", "!=", 0),
        ])
        extra_loc_ids = set(quants_here.location_id.ids) - known_loc_ids

        locations = []
        for loc_id in (known_loc_ids | extra_loc_ids):
            loc = self.env["stock.location"].browse(loc_id)
            wh = wh_loc_map.get(loc_id)
            locations.append({
                "location_id": loc_id,
                "location_name": loc.display_name,
                "warehouse_id": wh.id if wh else False,
                "warehouse_name": wh.name if wh else "—",
            })
        locations.sort(key=lambda r: (r["warehouse_name"], r["location_name"]))

        return {
            "warehouses": [{"warehouse_id": w.id, "warehouse_name": w.name} for w in warehouses],
            "locations": locations,
        }
