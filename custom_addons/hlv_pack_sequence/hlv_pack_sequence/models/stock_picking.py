from odoo import api, fields, models

class StockPicking(models.Model):
    _inherit = "stock.picking"

    # Tập các kiện của phiếu (lấy từ move lines -> result_package_id)
    package_ids = fields.Many2many(
        "stock.quant.package",
        string="Packages",
        compute="_compute_package_ids",
    )

    def _compute_package_ids(self):
        for picking in self:
            packs = picking.move_line_ids.mapped("result_package_id").ids
            # loại None, loại trùng
            packs = list(dict.fromkeys([pid for pid in packs if pid]))
            picking.package_ids = [(6, 0, packs)]
