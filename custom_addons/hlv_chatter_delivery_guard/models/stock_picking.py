# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


OUTBOUND_SEQUENCE_TOKENS = ("PICK", "PACK", "OUT", "SHIP", "DELIVERY")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _hlv_is_outbound_delivery_step(self):
        self.ensure_one()

        source_usage = self.location_id.usage
        destination_usage = self.location_dest_id.usage
        # A customer return can reuse an OUT operation type. It moves in the
        # opposite direction and must not be blocked by this outbound rule.
        if source_usage == "customer" and destination_usage in ("internal", "transit"):
            return False

        sequence_code = (self.picking_type_id.sequence_code or "").upper()
        if self.picking_type_code == "outgoing":
            return True
        return any(token in sequence_code for token in OUTBOUND_SEQUENCE_TOKENS)

    def _hlv_delivery_partners(self):
        """Collect both the picking contact and contacts carried by its SO."""
        self.ensure_one()
        partners = self.partner_id
        sale_orders = self.sale_id | self.move_ids.mapped("sale_line_id.order_id")
        partners |= sale_orders.mapped("partner_id")
        partners |= sale_orders.mapped("partner_shipping_id")
        return partners.exists()

    def _hlv_check_outbound_delivery_partner(self):
        for picking in self:
            if not picking._hlv_is_outbound_delivery_step():
                continue
            for partner in picking._hlv_delivery_partners():
                block_source = partner._hlv_outbound_delivery_block_source()
                if not block_source:
                    continue
                if block_source == partner:
                    reason = _("liên hệ này đã được đánh dấu không được xuất hàng")
                else:
                    reason = _(
                        "liên hệ cha %(partner)s đã được đánh dấu không được xuất hàng",
                        partner=block_source.display_name,
                    )
                raise UserError(
                    _(
                        "Không thể xử lý phiếu %(picking)s cho %(customer)s: %(reason)s.",
                        picking=picking.display_name,
                        customer=partner.display_name,
                        reason=reason,
                    )
                )
        return True

    def action_assign(self):
        self._hlv_check_outbound_delivery_partner()
        return super().action_assign()

    def button_validate(self):
        self._hlv_check_outbound_delivery_partner()
        return super().button_validate()

    def _action_done(self):
        # Keep the guard at the final model boundary as barcode/custom API code
        # may bypass button_validate() and call the completion method directly.
        self._hlv_check_outbound_delivery_partner()
        return super()._action_done()


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, *args, **kwargs):
        # This is the lowest stock boundary. Keep it protected for custom code
        # which completes moves without going through stock.picking methods.
        self.mapped("picking_id")._hlv_check_outbound_delivery_partner()
        return super()._action_done(*args, **kwargs)
