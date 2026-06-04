from odoo import api, models

class HlvStockQuick(models.TransientModel):
    _name = "hlv.stock.quick"
    _description = "Xem ton kho theo nhom"

    @api.model
    def get_data(
        self,
        group_id,
        warehouse_ids,
        show_zero,
        include_outgoing=True,
        extra_cols=None,
        stock_query="",
        offset=0,
        limit=None,
    ):
        if not group_id:
            return {"lines": [], "total": 0.0, "outgoing_total": 0.0, "columns": [], "total_count": 0}
        extra_cols = extra_cols or []
        group = self.env["hlv.product.report.group"].browse(group_id)
        products = group.product_ids.sorted("default_code")
        stock_query = (stock_query or "").strip().lower()
        if stock_query:
            products = products.filtered(
                lambda p: stock_query in (p.default_code or "").lower()
                or stock_query in (p.name or "").lower()
                or stock_query in (p.uom_id.name or "").lower()
            )
        if warehouse_ids:
            warehouses = self.env["stock.warehouse"].browse(warehouse_ids)
            columns = [{"id": wh.id, "name": wh.name} for wh in warehouses]
        else:
            warehouses = []
            columns = []
        # Pre-compute outgoing location ids per warehouse (pack zone + output zone)
        wh_outgoing_locs = {}
        if include_outgoing and warehouses:
            for wh in warehouses:
                ids = []
                for loc in [wh.wh_pack_stock_loc_id, wh.wh_output_stock_loc_id]:
                    if loc:
                        children = self.env["stock.location"].search([("id", "child_of", loc.id)])
                        ids.extend(children.ids)
                wh_outgoing_locs[wh.id] = ids
        if limit and not show_zero and products:
            visible_product_ids = set()
            product_domain = [("product_id", "in", products.ids)]
            if warehouses:
                stock_loc_ids = warehouses.mapped("lot_stock_id").ids
                stock_locs = self.env["stock.location"].search([
                    ("id", "child_of", stock_loc_ids),
                    ("usage", "=", "internal"),
                ])
                stock_domain = product_domain + [
                    ("location_id", "in", stock_locs.ids),
                    ("quantity", "!=", 0),
                ]
            else:
                stock_domain = product_domain + [
                    ("location_id.usage", "=", "internal"),
                    ("quantity", "!=", 0),
                ]
            stock_groups = self.env["stock.quant"].read_group(
                stock_domain,
                ["product_id", "quantity:sum"],
                ["product_id"],
            )
            visible_product_ids.update(
                row["product_id"][0]
                for row in stock_groups
                if row.get("product_id") and row.get("quantity")
            )
            if include_outgoing and wh_outgoing_locs:
                outgoing_loc_ids = list({
                    loc_id
                    for loc_ids in wh_outgoing_locs.values()
                    for loc_id in loc_ids
                })
                if outgoing_loc_ids:
                    outgoing_groups = self.env["stock.quant"].read_group(
                        product_domain + [
                            ("location_id", "in", outgoing_loc_ids),
                            ("quantity", ">", 0),
                        ],
                        ["product_id", "quantity:sum"],
                        ["product_id"],
                    )
                    visible_product_ids.update(
                        row["product_id"][0]
                        for row in outgoing_groups
                        if row.get("product_id") and row.get("quantity")
                    )
            products = products.filtered(lambda p: p.id in visible_product_ids)
        total_count = len(products)
        if limit:
            products = products[offset:offset + limit]
        # Pre-compute extra column data
        product_ids_list = products.ids
        extra_data = {}
        _direct_price_fields = {
            "sale_price": "lst_price",
            "price_web": "x_studio_ga_web",
            "price_listed": "x_studio_ga_hng_nim_yt",
            "price_tmdt": "x_studio_gia_san_tmdt",
            "price_commercial": "x_studio_gi_bn_thng_mi",
        }
        _direct_keys = [k for k in extra_cols if k in _direct_price_fields]
        if _direct_keys:
            for product in products:
                tmpl = product.product_tmpl_id
                d = extra_data.setdefault(product.id, {})
                for key in _direct_keys:
                    fname = _direct_price_fields[key]
                    d[key] = getattr(tmpl, fname, None) or getattr(product, fname, None) or 0.0
        if "purchase_price" in extra_cols:
            po_lines = self.env["purchase.order.line"].search([
                ("product_id", "in", product_ids_list),
                ("order_id.state", "in", ["purchase", "done"]),
            ], order="id desc")
            seen_pp = set()
            for pl in po_lines:
                pid = pl.product_id.id
                if pid not in seen_pp:
                    extra_data.setdefault(pid, {})["purchase_price"] = pl.price_unit
                    seen_pp.add(pid)
        if "sales_cycle" in extra_cols:
            from datetime import datetime, timedelta
            from collections import defaultdict
            date_from = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
            so_lines = self.env["sale.order.line"].search([
                ("product_id", "in", product_ids_list),
                ("order_id.state", "in", ["sale", "done"]),
                ("order_id.date_order", ">=", date_from),
            ])
            sale_order_sets = defaultdict(set)
            for sl in so_lines:
                sale_order_sets[sl.product_id.id].add(sl.order_id.id)
            for pid in product_ids_list:
                count = len(sale_order_sets.get(pid, set()))
                extra_data.setdefault(pid, {})["sales_cycle"] = round(90.0 / count, 1) if count > 0 else None
        if "avg_cost" in extra_cols:
            for product in products:
                layers_data = self.get_product_cost_layers(product.id, warehouse_ids)
                computed_avg = layers_data.get("computed_avg") or 0.0
                manual_avg_override = self._get_saved_manual_avg_override(product.id)
                if manual_avg_override is not None:
                    computed_avg = manual_avg_override
                    extra_data.setdefault(product.id, {})["avg_cost"] = manual_avg_override
                    extra_data[product.id]["manual_avg_override"] = True
                else:
                    extra_data.setdefault(product.id, {})["avg_cost"] = computed_avg
                extra_data.setdefault(product.id, {})["has_manual_layer"] = layers_data.get("has_manual_layer", False)
        if "incoming_qty" in extra_cols:
            # Only purchase order inbound moves not yet done
            in_moves = self.env["stock.move"].read_group(
                [
                    ("product_id", "in", product_ids_list),
                    ("state", "in", ["waiting", "confirmed", "assigned"]),
                    ("location_dest_id.usage", "=", "internal"),
                    ("location_id.usage", "!=", "internal"),
                    ("purchase_line_id", "!=", False),
                ],
                ["product_id", "product_qty:sum"],
                ["product_id"],
            )
            for row in in_moves:
                pid = row["product_id"][0]
                extra_data.setdefault(pid, {})["incoming_qty"] = row["product_qty"]
        if "reserved_qty" in extra_cols:
            # Set 1: final ship step going to customer (1-step or completed pick/pack chain)
            out1 = self.env["stock.move"].read_group(
                [
                    ("product_id", "in", product_ids_list),
                    ("state", "in", ["waiting", "confirmed", "assigned"]),
                    ("location_dest_id.usage", "=", "customer"),
                    ("sale_line_id", "!=", False),
                ],
                ["product_id", "product_qty:sum"], ["product_id"],
            )
            # Set 2: orphan internal pick — sale-linked, no origin and no downstream move yet
            # (e.g. KBC/PICK going to staging area but ship move not yet created/linked)
            out2 = self.env["stock.move"].read_group(
                [
                    ("product_id", "in", product_ids_list),
                    ("state", "in", ["waiting", "confirmed", "assigned"]),
                    ("location_id.usage", "=", "internal"),
                    ("location_dest_id.usage", "=", "internal"),
                    ("sale_line_id", "!=", False),
                    ("move_orig_ids", "=", False),
                    ("move_dest_ids", "=", False),
                ],
                ["product_id", "product_qty:sum"], ["product_id"],
            )
            for row in out1:
                pid = row["product_id"][0]
                extra_data.setdefault(pid, {})["reserved_qty"] = row["product_qty"]
            for row in out2:
                pid = row["product_id"][0]
                ed = extra_data.setdefault(pid, {})
                ed["reserved_qty"] = ed.get("reserved_qty", 0) + row["product_qty"]
        lines = []
        total = 0.0
        outgoing_total = 0.0
        for product in products:
            if warehouses:
                col_qtys = []
                col_outgoing_qtys = []
                for wh in warehouses:
                    sq = product.with_context(location=wh.lot_stock_id.id).qty_available
                    col_qtys.append(sq)
                    oq = 0.0
                    if include_outgoing and wh_outgoing_locs.get(wh.id):
                        quants = self.env["stock.quant"].search([
                            ("product_id", "=", product.id),
                            ("location_id", "in", wh_outgoing_locs[wh.id]),
                            ("quantity", ">", 0),
                        ])
                        oq = sum(q.quantity for q in quants)
                    col_outgoing_qtys.append(oq)
                prod_total = sum(col_qtys)
                prod_outgoing = sum(col_outgoing_qtys)
            else:
                col_qtys = []
                col_outgoing_qtys = []
                prod_total = product.qty_available
                prod_outgoing = 0.0
            if not show_zero and prod_total == 0 and prod_outgoing == 0:
                continue
            total += prod_total
            outgoing_total += prod_outgoing
            line_extra = {key: extra_data.get(product.id, {}).get(key) for key in extra_cols}
            line_extra["manual_avg_override"] = extra_data.get(product.id, {}).get("manual_avg_override", False)
            line_extra["has_manual_layer"] = extra_data.get(product.id, {}).get("has_manual_layer", False)
            # incoming_qty column shows on_hand + pending PO qty (projected after receiving)
            if "incoming_qty" in line_extra and line_extra["incoming_qty"] is not None:
                line_extra["incoming_pending"] = line_extra["incoming_qty"]  # raw pending for breakdown display
                line_extra["incoming_qty"] = prod_total + line_extra["incoming_qty"]
            else:
                line_extra["incoming_pending"] = 0
            lines.append({
                "id": product.id,
                "code": product.default_code or "",
                "name": product.name,
                "uom": product.uom_id.name or "",
                "image_url": "/web/image/product.product/%d/image_128" % product.id,
                "col_qtys": col_qtys,
                "col_outgoing_qtys": col_outgoing_qtys,
                "total": prod_total,
                "outgoing_total": prod_outgoing,
                "extra": line_extra,
            })
        return {
            "lines": lines,
            "total": total,
            "outgoing_total": outgoing_total,
            "columns": columns,
            "total_count": total_count,
        }

