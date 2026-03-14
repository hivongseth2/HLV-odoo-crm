import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

PICKING_STATE_LABELS = {
    "draft": "Nháp",
    "waiting": "Chờ hoạt động khác",
    "confirmed": "Chờ",
    "assigned": "Sẵn sàng",
    "done": "Hoàn thành",
    "cancel": "Hủy",
}


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _monitor_get_event_type(self):
        """Determine event type from picking type code."""
        self.ensure_one()
        code = (self.picking_type_id.sequence_code or "").upper()
        picking_code = self.picking_type_code

        if "PICK" in code:
            return "pick"
        elif "PACK" in code:
            return "pack"
        elif picking_code == "outgoing" or "OUT" in code:
            return "out"
        elif picking_code == "incoming" or "IN" in code:
            return "in"
        elif picking_code == "internal":
            return "internal"
        return "internal"

    def _monitor_find_related_sale(self):
        """Find related sale order via origin, group, or move lines."""
        self.ensure_one()

        # 1) Direct sale_id relation
        if hasattr(self, "sale_id") and self.sale_id:
            return self.sale_id

        # 2) Via procurement group
        if self.group_id and hasattr(self.group_id, "sale_id") and self.group_id.sale_id:
            return self.group_id.sale_id

        # 3) Via move lines
        for move in self.move_ids:
            if hasattr(move, "sale_line_id") and move.sale_line_id:
                return move.sale_line_id.order_id

        # 4) Via origin field
        if self.origin:
            so = self.env["sale.order"].search(
                [("name", "=", self.origin.strip())], limit=1
            )
            if so:
                return so

        return self.env["sale.order"].browse()

    def _monitor_find_related_purchase(self):
        """Find related purchase order via origin."""
        self.ensure_one()
        if self.origin:
            po = self.env["purchase.order"].search(
                [("name", "=", self.origin.strip())], limit=1
            )
            if po:
                return po
        # Via move lines
        for move in self.move_ids:
            if hasattr(move, "purchase_line_id") and move.purchase_line_id:
                return move.purchase_line_id.order_id
        return self.env["purchase.order"].browse()

    def _monitor_build_product_summary(self):
        """Build a text summary of products in this picking."""
        self.ensure_one()
        lines = []
        for move in self.move_ids[:10]:  # max 10 products in summary
            lines.append("%s x %s" % (move.product_id.display_name, move.product_uom_qty))
        if len(self.move_ids) > 10:
            lines.append("... và %d sản phẩm khác" % (len(self.move_ids) - 10))
        return "\n".join(lines)

    def _monitor_build_suggestion(self, event_type, action):
        """Build suggestion text based on context."""
        self.ensure_one()
        suggestion = ""

        if event_type == "in" and action == "validate":
            # PO receipt completed → suggest PICK for related SO
            so = self._monitor_find_related_sale()
            po = self._monitor_find_related_purchase()
            origin_ref = po.name if po else (self.origin or "")

            if so:
                suggestion = (
                    "✅ Nhập kho hoàn thành cho %s (gốc: %s). "
                    "ĐỀ XUẤT: Lấy hàng (PICK) và đóng gói cho đơn bán %s ngay!"
                ) % (self.name, origin_ref, so.name)
            elif origin_ref:
                # Even without direct SO link, suggest checking origin
                suggestion = (
                    "✅ Nhập kho hoàn thành cho %s (gốc: %s). "
                    "Kiểm tra đơn bán liên quan để lấy hàng đóng gói."
                ) % (self.name, origin_ref)

        elif event_type == "pick" and action == "validate":
            so = self._monitor_find_related_sale()
            if so:
                suggestion = (
                    "✅ Lấy hàng hoàn thành cho %s (đơn %s). "
                    "ĐỀ XUẤT: Đóng gói (PACK) cho đơn bán %s."
                ) % (self.name, self.origin or "", so.name)

        elif event_type == "pack" and action == "validate":
            so = self._monitor_find_related_sale()
            if so:
                suggestion = (
                    "✅ Đóng gói hoàn thành cho %s. "
                    "ĐỀ XUẤT: Xuất kho (OUT) cho đơn bán %s."
                ) % (self.name, so.name)

        elif event_type == "out" and action == "validate":
            suggestion = (
                "✅ Xuất kho hoàn thành cho %s. Đơn hàng đã sẵn sàng giao."
            ) % self.name

        return suggestion

    def _monitor_log_picking_event(self, action, state_before=None, state_after=None):
        """Log a stock.picking event to the monitor."""
        MonitorEvent = self.env["warehouse.monitor.event"]
        for picking in self:
            warehouse = (
                picking.picking_type_id.warehouse_id
                if picking.picking_type_id
                else self.env["stock.warehouse"].browse()
            )
            if not warehouse:
                continue

            event_type = picking._monitor_get_event_type()
            so = picking._monitor_find_related_sale()
            po = picking._monitor_find_related_purchase()

            action_labels = {
                "create": "Tạo mới",
                "confirm": "Xác nhận",
                "assign": "Sẵn sàng",
                "validate": "Hoàn thành",
                "cancel": "Hủy",
            }
            action_label = action_labels.get(action, action)

            event_type_labels = {
                "pick": "PICK",
                "pack": "PACK",
                "out": "OUT",
                "in": "IN",
                "internal": "Chuyển nội bộ",
            }
            type_label = event_type_labels.get(event_type, event_type)

            state_label = PICKING_STATE_LABELS.get(
                state_after or picking.state, state_after or picking.state
            )

            summary = "[%s] %s - %s [%s] - Kho: %s" % (
                type_label,
                picking.name,
                action_label,
                state_label,
                warehouse.name,
            )
            if picking.origin:
                summary += " - Gốc: %s" % picking.origin
            if picking.partner_id:
                summary += " - ĐT: %s" % picking.partner_id.name

            suggestion = picking._monitor_build_suggestion(event_type, action)
            product_summary = picking._monitor_build_product_summary()

            priority = "medium"
            if suggestion:
                priority = "high"
            if action == "validate" and event_type == "in":
                priority = "high"
            if action == "cancel":
                priority = "urgent"

            MonitorEvent._log_event({
                "name": "[%s] %s - %s" % (type_label, picking.name, action_label),
                "event_type": event_type,
                "action": action,
                "warehouse_id": warehouse.id,
                "picking_id": picking.id,
                "sale_id": so.id if so else False,
                "purchase_id": po.id if po else False,
                "origin": picking.origin or "",
                "state_before": PICKING_STATE_LABELS.get(state_before, state_before) if state_before else "",
                "state_after": state_label,
                "summary": summary,
                "suggestion": suggestion,
                "priority": priority,
                "product_summary": product_summary,
                "picking_type_code": (picking.picking_type_id.sequence_code or ""),
            })

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        for picking in pickings:
            try:
                picking._monitor_log_picking_event("create", state_after=picking.state)
            except Exception:
                _logger.exception("[HLV Monitor] Error logging picking create: %s", picking.name)
        return pickings

    def action_assign(self):
        states_before = {p.id: p.state for p in self}
        result = super().action_assign()
        for picking in self:
            try:
                picking._monitor_log_picking_event(
                    "assign",
                    state_before=states_before.get(picking.id),
                    state_after=picking.state,
                )
            except Exception:
                _logger.exception("[HLV Monitor] Error logging picking assign: %s", picking.name)
        return result

    def button_validate(self):
        states_before = {p.id: p.state for p in self}
        result = super().button_validate()
        for picking in self:
            try:
                if picking.state == "done":
                    picking._monitor_log_picking_event(
                        "validate",
                        state_before=states_before.get(picking.id),
                        state_after=picking.state,
                    )
            except Exception:
                _logger.exception("[HLV Monitor] Error logging picking validate: %s", picking.name)
        return result

    def action_cancel(self):
        states_before = {p.id: p.state for p in self}
        result = super().action_cancel()
        for picking in self:
            try:
                picking._monitor_log_picking_event(
                    "cancel",
                    state_before=states_before.get(picking.id),
                    state_after=picking.state,
                )
            except Exception:
                _logger.exception("[HLV Monitor] Error logging picking cancel: %s", picking.name)
        return result
