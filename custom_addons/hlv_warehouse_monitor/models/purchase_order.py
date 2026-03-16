import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

STATE_LABELS = {
    "draft": "Yêu cầu báo giá",
    "sent": "Đã gửi",
    "to approve": "Chờ duyệt",
    "purchase": "Đơn mua hàng",
    "done": "Khóa",
    "cancel": "Hủy",
}


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _monitor_log_purchase_event(self, action, state_before=None, state_after=None):
        """Log a purchase order event to the monitor."""
        MonitorEvent = self.env["warehouse.monitor.event"]
        for order in self:
            # PO's picking_type_id.warehouse_id or default warehouse
            warehouse = False
            if order.picking_type_id and order.picking_type_id.warehouse_id:
                warehouse = order.picking_type_id.warehouse_id
            if not warehouse:
                warehouse = self.env["stock.warehouse"].search([], limit=1)
            if not warehouse:
                continue

            action_labels = {
                "create": "Tạo mới",
                "confirm": "Xác nhận",
                "cancel": "Hủy",
                "update": "Cập nhật",
            }
            action_label = action_labels.get(action, action)
            state_label = STATE_LABELS.get(state_after or order.state, state_after or order.state)

            summary = "Đơn mua %s - %s [%s] - Kho: %s" % (
                order.name,
                action_label,
                state_label,
                warehouse.name,
            )
            if order.partner_id:
                summary += " - NCC: %s" % order.partner_id.name

            # Link to related SO via origin
            suggestion = ""
            sale_id = False
            if order.origin:
                so = self.env["sale.order"].search(
                    [("name", "=", order.origin.strip())], limit=1
                )
                if so:
                    sale_id = so.id
                    if action == "confirm":
                        suggestion = (
                            "Đơn mua hàng %s (gốc: %s) đã xác nhận. "
                            "Khi nhập kho xong, hãy lấy hàng và đóng gói cho đơn bán %s."
                        ) % (order.name, order.origin, so.name)

            MonitorEvent._log_event({
                "name": "[PO] %s - %s" % (order.name, action_label),
                "event_type": "purchase",
                "action": action,
                "warehouse_id": warehouse.id,
                "purchase_id": order.id,
                "sale_id": sale_id,
                "origin": order.origin or order.name,
                "state_before": STATE_LABELS.get(state_before, state_before) if state_before else "",
                "state_after": state_label,
                "summary": summary,
                "suggestion": suggestion,
                "priority": "high" if suggestion else "medium",
            })

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            try:
                order._monitor_log_purchase_event("create", state_after=order.state)
            except Exception:
                _logger.exception("[HLV Monitor] Error logging PO create: %s", order.name)
        return orders

    def button_confirm(self):
        states_before = {order.id: order.state for order in self}
        result = super().button_confirm()
        for order in self:
            try:
                order._monitor_log_purchase_event(
                    "confirm",
                    state_before=states_before.get(order.id),
                    state_after=order.state,
                )
            except Exception:
                _logger.exception("[HLV Monitor] Error logging PO confirm: %s", order.name)
        return result

    def button_cancel(self):
        states_before = {order.id: order.state for order in self}
        result = super().button_cancel()
        for order in self:
            try:
                order._monitor_log_purchase_event(
                    "cancel",
                    state_before=states_before.get(order.id),
                    state_after=order.state,
                )
            except Exception:
                _logger.exception("[HLV Monitor] Error logging PO cancel: %s", order.name)
        return result
