from odoo import api, models


class HlvStockQuick(models.TransientModel):
    _inherit = 'hlv.stock.quick'

    @api.model
    def _get_saved_manual_avg_override(self, product_id):
        product = self.env["product.product"].sudo().browse(product_id).exists()
        if not product or not product.hlv_manual_avg_cost_enabled:
            return None
        return float(product.hlv_manual_avg_cost or 0.0)

    @api.model
    def _get_saved_manual_layer_amounts(self, product_id):
        po_lines = self.env["purchase.order.line"].sudo().search([
            ("product_id", "=", product_id),
            ("hlv_manual_cost_total_enabled", "=", True),
        ])
        return {line.id: float(line.hlv_manual_cost_total or 0.0) for line in po_lines}

    @api.model
    def save_manual_overrides(self, product_id, avg_cost=None, layer_amounts=None):
        product = self.env["product.product"].sudo().browse(product_id).exists()
        if product:
            if avg_cost is None:
                product.write({
                    "hlv_manual_avg_cost_enabled": False,
                    "hlv_manual_avg_cost": 0.0,
                })
            else:
                product.write({
                    "hlv_manual_avg_cost_enabled": True,
                    "hlv_manual_avg_cost": float(avg_cost),
                })

        normalized_layers = {}
        if isinstance(layer_amounts, dict):
            for layer_id, amount in layer_amounts.items():
                try:
                    normalized_layers[int(layer_id)] = float(amount)
                except (TypeError, ValueError):
                    continue

        existing_lines = self.env["purchase.order.line"].sudo().search([
            ("product_id", "=", product_id),
            ("hlv_manual_cost_total_enabled", "=", True),
        ])
        kept_line_ids = set(normalized_layers)
        lines_to_reset = existing_lines.filtered(lambda line: line.id not in kept_line_ids)
        if lines_to_reset:
            lines_to_reset.write({
                "hlv_manual_cost_total_enabled": False,
                "hlv_manual_cost_total": 0.0,
            })
        if normalized_layers:
            po_lines = self.env["purchase.order.line"].sudo().browse(list(normalized_layers)).exists()
            for po_line in po_lines.filtered(lambda line: line.product_id.id == product_id):
                po_line.write({
                    "hlv_manual_cost_total_enabled": True,
                    "hlv_manual_cost_total": normalized_layers[po_line.id],
                })

        return {
            "avg_cost": self._get_saved_manual_avg_override(product_id),
            "layer_amounts": self._get_saved_manual_layer_amounts(product_id),
        }

    @api.model
    def get_product_cost_layers(self, product_id, warehouse_ids=None):
        """Return PO-line layers for avg cost using gross line total (incl. tax), preserving manual overrides."""
        product = self.env["product.product"].browse(product_id)
        if warehouse_ids:
            warehouses = self.env["stock.warehouse"].browse(warehouse_ids)
            on_hand_qty = sum(product.with_context(location=wh.lot_stock_id.id).qty_available for wh in warehouses)
        else:
            on_hand_qty = product.qty_available
        manual_layer_amounts = self._get_saved_manual_layer_amounts(product_id)
        manual_avg_override = self._get_saved_manual_avg_override(product_id)

        po_lines = self.env["purchase.order.line"].search(
            [
                ("product_id", "=", product_id),
                ("state", "in", ["purchase", "done"]),
                ("product_qty", ">", 0),
                ("qty_received", ">", 0),
            ],
            order="date_planned desc, id desc",
        )

        rows = []
        remaining = on_hand_qty
        from datetime import timedelta
        for po_line in po_lines:
            ordered_qty = float(po_line.product_qty or 0.0)
            received_qty = float(po_line.qty_received or 0.0)
            if ordered_qty <= 0 or received_qty <= 0:
                continue
            if remaining <= 0.001:
                break

            qty_take = min(received_qty, remaining)
            remaining -= qty_take

            subtotal = float(po_line.price_subtotal or 0.0)
            line_total = float(po_line.price_total or 0.0)
            tax_amount = float(po_line.price_tax or (line_total - subtotal))
            if not line_total:
                line_total = subtotal + tax_amount
            if not tax_amount and line_total:
                tax_amount = line_total - subtotal

            allocated_subtotal = subtotal * qty_take / ordered_qty if ordered_qty else 0.0
            allocated_tax = tax_amount * qty_take / ordered_qty if ordered_qty else 0.0
            allocated_value = line_total * qty_take / ordered_qty if ordered_qty else 0.0
            unit_cost = line_total / ordered_qty if ordered_qty else 0.0
            unit_cost_before_tax = subtotal / ordered_qty if ordered_qty else 0.0
            tax_per_unit = tax_amount / ordered_qty if ordered_qty else 0.0

            manual_amount = manual_layer_amounts.get(po_line.id)
            if manual_amount is not None:
                line_total = float(manual_amount)
                tax_amount = max(line_total - allocated_subtotal, 0.0)
                allocated_tax = tax_amount * qty_take / received_qty if received_qty else 0.0
                allocated_value = line_total * qty_take / received_qty if received_qty else 0.0
                unit_cost = line_total / received_qty if received_qty else 0.0
                is_manual = True
                stored_manual_amount = round(line_total, 2)
            else:
                is_manual = False
                stored_manual_amount = None

            dt_planned = po_line.date_planned + timedelta(hours=7) if po_line.date_planned else None
            dt_order = po_line.order_id.date_order + timedelta(hours=7) if po_line.order_id.date_order else None
            date_str = dt_planned.strftime("%d/%m/%Y") if dt_planned else (dt_order.strftime("%d/%m/%Y") if dt_order else "")

            rows.append({
                "id": po_line.id,
                "date": date_str,
                "reference": po_line.order_id.name or "",
                "po_name": po_line.order_id.partner_id.display_name if po_line.order_id.partner_id else "",
                "qty": round(qty_take, 2),
                "line_qty": round(received_qty, 2),
                "ordered_qty": round(ordered_qty, 2),
                "received_qty": round(received_qty, 2),
                "unit_cost_before_tax": round(unit_cost_before_tax, 2),
                "unit_cost": round(unit_cost, 2),
                "value": round(allocated_value, 2),
                "tax_value": round(allocated_tax, 2),
                "tax_per_unit": round(tax_per_unit, 2),
                "price_total": round(line_total, 2),
                "price_tax": round(tax_amount, 2),
                "price_subtotal": round(subtotal, 2),
                "uom": po_line.product_uom.name if po_line.product_uom else "",
                "allocated_subtotal": round(allocated_subtotal, 2),
                "is_manual": is_manual,
                "manual_amount": stored_manual_amount,
            })

        total_qty = sum(r["qty"] for r in rows)
        total_tax = sum(r["tax_value"] for r in rows)
        total_value = sum(r["value"] for r in rows)
        if manual_avg_override is not None:
            computed_avg = float(manual_avg_override)
            total_value = round(computed_avg * total_qty, 2)
        else:
            computed_avg = total_value / total_qty if total_qty else 0.0
            total_value = round(total_value, 2)

        return {
            "layers": rows,
            "total_qty": total_qty,
            "total_value": round(total_value, 2),
            "total_tax": round(total_tax, 2),
            "computed_avg": round(computed_avg, 2),
            "manual_avg_override": manual_avg_override,
            "has_manual_layer": any(r.get("is_manual") for r in rows),
        }

    @api.model
    def get_product_pending_moves(self, product_id, key, warehouse_ids):
        """Return list of pending stock moves for incoming_qty or reserved_qty panel."""
        if key == "incoming_qty":
            domain = [
                ("product_id", "=", product_id),
                ("state", "in", ["waiting", "confirmed", "assigned"]),
                ("location_dest_id.usage", "=", "internal"),
                ("location_id.usage", "!=", "internal"),
                ("purchase_line_id", "!=", False),
            ]
        elif key == "reserved_qty":
            # Set 1: final ship to customer
            domain_r1 = [
                ("product_id", "=", product_id),
                ("state", "in", ["waiting", "confirmed", "assigned"]),
                ("location_dest_id.usage", "=", "customer"),
                ("sale_line_id", "!=", False),
            ]
            # Set 2: orphan internal pick (no origin, no destination move)
            domain_r2 = [
                ("product_id", "=", product_id),
                ("state", "in", ["waiting", "confirmed", "assigned"]),
                ("location_id.usage", "=", "internal"),
                ("location_dest_id.usage", "=", "internal"),
                ("sale_line_id", "!=", False),
                ("move_orig_ids", "=", False),
                ("move_dest_ids", "=", False),
            ]
            moves = (
                self.env["stock.move"].search(domain_r1, order="date asc", limit=100)
                | self.env["stock.move"].search(domain_r2, order="date asc", limit=100)
            ).sorted("date")
        else:
            return []
        state_labels = {"waiting": "Đang chờ", "confirmed": "Đã xác nhận", "assigned": "Sẵn sàng"}
        if key != "reserved_qty":
            moves = self.env["stock.move"].search(domain, order="date asc", limit=100)
        result = []
        for m in moves:
            result.append({
                "picking_name": m.picking_id.name if m.picking_id else (m.name or ""),
                "origin": (m.picking_id.origin if m.picking_id else None) or m.origin or "",
                "state": state_labels.get(m.state, m.state),
                "qty": m.product_uom_qty,
                "uom": m.product_uom.name if m.product_uom else "",
                "date": m.date.strftime("%d/%m/%Y") if m.date else "",
                "partner": (m.picking_id.partner_id.name if m.picking_id and m.picking_id.partner_id else "") or "",
            })
        return result
