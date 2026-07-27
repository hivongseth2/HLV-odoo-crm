# -*- coding: utf-8 -*-

from odoo import _
from odoo.tools.float_utils import float_compare


class ProductMergeBlockerMixin:
    def _format_qty(self, qty):
        qty = float(qty or 0.0)
        if qty.is_integer():
            return str(int(qty))
        return ("%.6f" % qty).rstrip("0").rstrip(".")

    def _append_blocker(self, blockers, label, entries):
        if not entries:
            return
        sample = ", ".join(entries[:5])
        more = "... (+%s)" % (len(entries) - 5) if len(entries) > 5 else ""
        blockers.append("%s: %s%s" % (label, sample, more))

    def _get_sale_blockers(self, product, rounding):
        entries = []
        lines = self.env["sale.order.line"].search([
            ("product_id", "=", product.id),
            ("state", "not in", ("cancel", "done")),
        ], limit=200)
        for line in lines:
            ordered_qty = float(line.product_uom_qty or 0.0)
            remaining_qty = ordered_qty - float(line.qty_delivered or 0.0)
            if float_compare(remaining_qty, 0.0, precision_rounding=rounding) <= 0:
                continue
            active_moves = line.move_ids.filtered(lambda move: move.state != "cancel")
            if active_moves and not active_moves.filtered(lambda move: move.state != "done"):
                continue
            entries.append(
                "%s (còn giao %s/%s)"
                % (
                    line.order_id.display_name,
                    self._format_qty(remaining_qty),
                    self._format_qty(ordered_qty),
                )
            )
        return entries

    def _get_purchase_blockers(self, product, rounding):
        entries = []
        lines = self.env["purchase.order.line"].search([
            ("product_id", "=", product.id),
            ("state", "not in", ("cancel", "done")),
        ], limit=200)
        for line in lines:
            ordered_qty = float(line.product_qty or 0.0)
            remaining_qty = ordered_qty - float(line.qty_received or 0.0)
            if float_compare(remaining_qty, 0.0, precision_rounding=rounding) <= 0:
                continue
            active_moves = line.move_ids.filtered(lambda move: move.state != "cancel")
            if active_moves and not active_moves.filtered(lambda move: move.state != "done"):
                continue
            entries.append(
                "%s (còn nhận %s/%s)"
                % (
                    line.order_id.display_name,
                    self._format_qty(remaining_qty),
                    self._format_qty(ordered_qty),
                )
            )
        return entries

    def _get_stock_move_blockers(self, product):
        move_model = self.env["stock.move"]
        domain = [
            ("product_id", "=", product.id),
            ("state", "not in", ("cancel", "done")),
        ]
        if "sale_line_id" in move_model._fields:
            domain.append(("sale_line_id", "=", False))
        if "purchase_line_id" in move_model._fields:
            domain.append(("purchase_line_id", "=", False))
        return [
            move.picking_id.display_name
            or move.reference
            or move.origin
            or move.display_name
            for move in move_model.search(domain, limit=200)
        ]

    def _get_merge_blockers(self, product):
        if not product:
            return []
        blockers = []
        rounding = product.uom_id.rounding or 0.00001
        self._append_blocker(
            blockers,
            _("Đơn bán chưa giao đủ"),
            self._get_sale_blockers(product, rounding),
        )
        self._append_blocker(
            blockers,
            _("Đơn mua chưa nhận đủ"),
            self._get_purchase_blockers(product, rounding),
        )
        self._append_blocker(
            blockers,
            _("Phiếu kho/chuyển kho chưa hoàn tất"),
            self._get_stock_move_blockers(product),
        )

        reserved_quants = self.env["stock.quant"].search([
            ("product_id", "=", product.id),
            ("reserved_quantity", ">", 0),
        ], limit=6)
        if reserved_quants:
            locations = reserved_quants[:5].mapped("location_id.display_name")
            suffix = "..." if len(reserved_quants) > 5 else ""
            blockers.append(
                _("Tồn kho đang được giữ chỗ tại: %s%s")
                % (", ".join(locations), suffix)
            )
        return blockers
