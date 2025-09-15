from odoo import models

class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_open_order_in_panel(self):
        self.ensure_one()
        try:
            # BẮT BUỘC luôn trả action hợp lệ
            return {
                "type": "ir.actions.client",
                "tag": "hlv_show_panel_noqweb",
                "context": dict(self.env.context, active_id=self.id),
                # hoặc "params": {"res_id": self.id}
            }
        except Exception:
            # fallback no-op để KHÔNG BAO GIỜ trả None
            return {"type": "ir.actions.act_window_close"}
