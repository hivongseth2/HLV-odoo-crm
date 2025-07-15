from odoo import models, api

class StockPicking(models.Model):
    _inherit = "stock.picking"

    @api.model
    def _get_next_picking_from_barcode(self, barcode):
        picking = self.search([('name', '=', barcode)], limit=1)
        if not picking:
            return {"error": "Không tìm thấy phiếu với mã vạch đã quét."}

        if picking.state != 'done':
            return {{
                "type": "ir.actions.act_window",
                "res_model": "stock.picking",
                "res_id": picking.id,
                "view_mode": "form",
                "target": "current"
            }}

        # Nếu phiếu đã done, tìm phiếu tiếp theo cùng group
        if picking.group_id:
            next_picking = self.search([
                ('group_id', '=', picking.group_id.id),
                ('state', 'not in', ['done', 'cancel']),
                ('id', '!=', picking.id)
            ], order='scheduled_date asc', limit=1)

            if next_picking:
                return {{
                    "type": "ir.actions.act_window",
                    "res_model": "stock.picking",
                    "res_id": next_picking.id,
                    "view_mode": "form",
                    "target": "current"
                }}

        return {{
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {{
                "title": "Thông báo",
                "message": "Tất cả các bước trong luồng này đã hoàn thành.",
                "sticky": False,
            }}
        }}