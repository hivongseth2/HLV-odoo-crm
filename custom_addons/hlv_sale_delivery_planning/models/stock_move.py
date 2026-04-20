import logging
from odoo import models

_logger = logging.getLogger(__name__)

# Move state changes that affect dashboard stock/packing status
_MOVE_NOTIFY_FIELDS = {'state', 'quantity', 'picked'}


class StockMove(models.Model):
    _inherit = 'stock.move'

    def write(self, vals):
        res = super().write(vals)
        if vals and _MOVE_NOTIFY_FIELDS.intersection(vals.keys()):
            # Only notify for moves linked to sale orders (avoid noise from internal/MRP moves)
            if any(m.sale_line_id or (m.picking_id and m.picking_id.sale_id) for m in self[:5]):
                self._notify_delivery_planner_changed()
        return res

    def _action_assign(self, *args, **kwargs):
        res = super()._action_assign(*args, **kwargs)
        # Reservation changed → stock status on dashboard may change
        if any(m.sale_line_id or (m.picking_id and m.picking_id.sale_id) for m in self[:5]):
            self._notify_delivery_planner_changed()
        return res

    def _do_unreserve(self):
        # Check before unreserve (recordset still has data)
        should_notify = any(m.sale_line_id or (m.picking_id and m.picking_id.sale_id) for m in self[:5])
        res = super()._do_unreserve()
        if should_notify:
            self._notify_delivery_planner_changed()
        return res

    def _notify_delivery_planner_changed(self):
        """Send bus notification so the delivery planner dashboard refreshes instantly."""
        try:
            self.env['bus.bus']._sendone(
                'delivery_planner_channel',
                'delivery_planner_data_changed',
                {'source': 'stock.move'},
            )
        except Exception:
            _logger.debug('Failed to send delivery_planner_data_changed notification', exc_info=True)
