from odoo import api, models


class HlvStockQuick(models.TransientModel):
    _inherit = 'hlv.stock.quick'

    def _detect_combo_for_move(self, move, sale_line):
        """Try to find the combo/kit parent for a move with price=0.
        Returns dict {name, code, price} or None.
        Tries sale_line.order_id first, then picking.sale_id as fallback.
        """
        try:
            BomLine = self.env.get("mrp.bom.line")
            if not BomLine:
                return None
            # Find kit BOMs that contain this product.
            bom_lines = BomLine.search([
                ("product_id", "=", move.product_id.id),
                ("bom_id.type", "=", "phantom"),
            ], limit=10)
            if not bom_lines:
                return None
            kit_tmpl_ids = set(bom_lines.mapped("bom_id.product_tmpl_id").ids)

            # Resolve sale order: try sale_line first, then picking.sale_id
            order = False
            if sale_line:
                order = sale_line.order_id
            if not order:
                picking = move.picking_id
                if picking:
                    order = getattr(picking, "sale_id", False)

            if order:
                parent_line = order.order_line.filtered(
                    lambda l: l.product_id.product_tmpl_id.id in kit_tmpl_ids
                    and l.price_unit > 0
                )
                if parent_line:
                    pl = parent_line[0]
                    return {
                        "name": pl.product_id.name,
                        "code": pl.product_id.default_code or "",
                        "price": pl.price_unit,
                    }

            # BOM exists but can't find parent line — still mark as combo
            bom = bom_lines[0].bom_id
            return {
                "name": bom.product_tmpl_id.name,
                "code": bom.product_tmpl_id.default_code or "",
                "price": 0.0,
            }
        except Exception:
            pass
        return None

    @api.model
    def get_product_moves(self, product_id, warehouse_ids, date_from=None, date_to=None):
        from datetime import datetime, timedelta
        # UTC+7 (Asia/Ho_Chi_Minh)
        try:
            import pytz
            tz_vn = pytz.timezone("Asia/Ho_Chi_Minh")
            now_local = datetime.now(tz_vn)
        except ImportError:
            tz_vn = None
            now_local = datetime.utcnow() + timedelta(hours=7)

        if not date_from:
            date_from = now_local.strftime("%Y-%m-01")
        if not date_to:
            date_to = now_local.strftime("%Y-%m-%d")

        def local_to_utc_start(d_str):
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            if tz_vn:
                import pytz as _pytz
                return tz_vn.localize(dt).astimezone(_pytz.utc).replace(tzinfo=None)
            return dt - timedelta(hours=7)

        def local_to_utc_end(d_str):
            dt = datetime.strptime(d_str + " 23:59:59", "%Y-%m-%d %H:%M:%S")
            if tz_vn:
                import pytz as _pytz
                return tz_vn.localize(dt).astimezone(_pytz.utc).replace(tzinfo=None)
            return dt - timedelta(hours=7)

        def utc_to_local_str(dt_utc):
            if not dt_utc:
                return ""
            if tz_vn:
                import pytz as _pytz
                dt = _pytz.utc.localize(dt_utc.replace(tzinfo=None)).astimezone(tz_vn)
            else:
                dt = dt_utc + timedelta(hours=7)
            return dt.strftime("%d/%m/%Y")

        date_from_utc = local_to_utc_start(date_from)
        date_to_utc = local_to_utc_end(date_to)
        date_from_str = date_from_utc.strftime("%Y-%m-%d %H:%M:%S")
        date_to_str = date_to_utc.strftime("%Y-%m-%d %H:%M:%S")

        # Warehouse stock locations — include pack + output zones so that
        # 3-step delivery moves (PICK stock→pack, PACK pack→output) are treated
        # as internal (both ends in set) and only OUT (output→customer) is counted.
        if warehouse_ids:
            warehouses = self.env["stock.warehouse"].browse(warehouse_ids)
            all_loc_ids = []
            for wh in warehouses:
                locs = self.env["stock.location"].search([
                    ("id", "child_of", wh.lot_stock_id.id),
                    ("usage", "=", "internal"),
                ])
                all_loc_ids.extend(locs.ids)
                if wh.wh_pack_stock_loc_id:
                    pack_locs = self.env["stock.location"].search([
                        ("id", "child_of", wh.wh_pack_stock_loc_id.id),
                    ])
                    all_loc_ids.extend(pack_locs.ids)
                if wh.wh_output_stock_loc_id:
                    out_locs = self.env["stock.location"].search([
                        ("id", "child_of", wh.wh_output_stock_loc_id.id),
                    ])
                    all_loc_ids.extend(out_locs.ids)
            all_loc_ids = list(set(all_loc_ids))
        else:
            all_loc_ids = self.env["stock.location"].search([("usage", "=", "internal")]).ids
        all_loc_set = set(all_loc_ids)

        product = self.env["product.product"].browse(product_id)

        # Opening balance using to_date context (tồn đầu kỳ)
        try:
            opening = product.with_context(
                location=all_loc_ids,
                to_date=date_from_str,
            ).qty_available
        except Exception:
            opening = 0.0

        # Moves in date range
        moves = self.env["stock.move"].search([
            ("product_id", "=", product_id),
            ("state", "=", "done"),
            ("date", ">=", date_from_str),
            ("date", "<=", date_to_str),
            "|",
            ("location_dest_id", "in", all_loc_ids),
            ("location_id", "in", all_loc_ids),
        ], order="date asc, id asc")

        result_moves = []
        running = opening

        for move in moves:
            is_dest = move.location_dest_id.id in all_loc_set
            is_src = move.location_id.id in all_loc_set
            if is_dest and is_src:
                continue  # internal transfer within warehouse

            qty = float(getattr(move, "quantity", 0) or getattr(move, "quantity_done", 0) or 0)
            if qty <= 0:
                continue

            if is_dest:
                move_type = "in"
                running += qty
                in_qty = qty
                out_qty = 0.0
            else:
                move_type = "out"
                running -= qty
                in_qty = 0.0
                out_qty = qty

            # Price + combo detection
            price = 0.0
            combo_info = None
            purchase_line = getattr(move, "purchase_line_id", False)
            sale_line = getattr(move, "sale_line_id", False)
            if purchase_line:
                price = purchase_line.price_unit or 0.0
            elif sale_line:
                # Phantom kit: sale_line points to the combo product, not the component
                if sale_line.product_id.id != move.product_id.id:
                    price = 0.0
                    combo_info = {
                        "name": sale_line.product_id.name,
                        "code": sale_line.product_id.default_code or "",
                        "price": sale_line.price_unit,
                    }
                else:
                    price = sale_line.price_unit or 0.0
            else:
                price = getattr(move, "price_unit", 0.0) or 0.0
            # Fallback combo detection for moves without sale_line (price still 0)
            if price == 0.0 and move_type == "out" and not combo_info:
                combo_info = self._detect_combo_for_move(move, sale_line)

            picking = move.picking_id
            partner = picking.partner_id if picking else False

            # Transit transfer detection (deltatech_picking_transit)
            is_transit = False
            transit_linked = ""  # tên phiếu liên kết bên kia
            if picking:
                source_tf = getattr(picking, "source_transfer_id", False)
                second_created = getattr(picking, "second_transfer_created", False)
                src_usage = move.location_id.usage
                dst_usage = move.location_dest_id.usage
                if source_tf:
                    # Bước 2: phiếu nhận từ transit
                    is_transit = True
                    transit_linked = source_tf.name or ""
                elif second_created:
                    # Bước 1: phiếu xuất sang transit, tìm phiếu bước 2
                    is_transit = True
                    step2 = self.env["stock.picking"].search(
                        [("source_transfer_id", "=", picking.id)], limit=1
                    )
                    transit_linked = step2.name if step2 else ""
                elif src_usage == "transit" or dst_usage == "transit":
                    is_transit = True

            # Build origin: show linked transit picking name if applicable
            if is_transit and transit_linked:
                origin = transit_linked
            else:
                origin = (picking.origin if picking else "") or ""

            # Description
            if is_transit:
                description = "Nhập chuyển kho" if move_type == "in" else "Xuất chuyển kho"
            else:
                description = "Nhập kho" if move_type == "in" else "Xuất kho"

            result_moves.append({
                "type": move_type,
                "is_transit": is_transit,
                "date": utc_to_local_str(move.date),
                "reference": (picking.name if picking else move.name) or "",
                "origin": origin,
                "description": description,
                "uom": move.product_uom.name or "",
                "price": price,
                "combo_info": combo_info,
                "in_qty": in_qty,
                "out_qty": out_qty,
                "balance": round(running, 4),
                "partner_code": (partner.ref or "") if partner else "",
                "partner_name": (partner.name or "") if partner else "",
            })

        return {
            "opening": opening,
            "moves": result_moves,
            "date_from": date_from,
            "date_to": date_to,
            "closing": round(running, 4),
        }
