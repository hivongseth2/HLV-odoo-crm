import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

STATE_LABELS = {
    "draft": "Báo giá",
    "sent": "Đã gửi",
    "sale": "Đơn hàng",
    "done": "Khóa",
    "cancel": "Hủy",
}


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _monitor_get_warehouse(self):
        """Get warehouse for this sale order."""
        self.ensure_one()
        return self.warehouse_id

    def _monitor_log_sale_event(self, action, state_before=None, state_after=None):
        """Log a sale order event to the monitor."""
        MonitorEvent = self.env["warehouse.monitor.event"]
        for order in self:
            warehouse = order._monitor_get_warehouse()
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

            summary = "Đơn bán %s - %s [%s] - Kho: %s" % (
                order.name,
                action_label,
                state_label,
                warehouse.name,
            )
            if order.partner_id:
                summary += " - KH: %s" % order.partner_id.name

            MonitorEvent._log_event({
                "name": "[SO] %s - %s" % (order.name, action_label),
                "event_type": "sale",
                "action": action,
                "warehouse_id": warehouse.id,
                "sale_id": order.id,
                "origin": order.name,
                "state_before": STATE_LABELS.get(state_before, state_before) if state_before else "",
                "state_after": state_label,
                "summary": summary,
                "priority": "high" if action == "confirm" else "medium",
            })

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            try:
                order._monitor_log_sale_event("create", state_after=order.state)
            except Exception:
                _logger.exception("[HLV Monitor] Error logging SO create: %s", order.name)
        return orders

    def action_confirm(self):
        states_before = {order.id: order.state for order in self}
        result = super().action_confirm()
        for order in self:
            try:
                order._monitor_log_sale_event(
                    "confirm",
                    state_before=states_before.get(order.id),
                    state_after=order.state,
                )
            except Exception:
                _logger.exception("[HLV Monitor] Error logging SO confirm: %s", order.name)
        return result

    def action_cancel(self):
        states_before = {order.id: order.state for order in self}
        result = super().action_cancel()
        for order in self:
            try:
                order._monitor_log_sale_event(
                    "cancel",
                    state_before=states_before.get(order.id),
                    state_after=order.state,
                )
            except Exception:
                _logger.exception("[HLV Monitor] Error logging SO cancel: %s", order.name)
        return result
