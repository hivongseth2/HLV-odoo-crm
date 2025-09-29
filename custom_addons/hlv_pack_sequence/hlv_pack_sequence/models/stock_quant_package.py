from odoo import api, fields, models

class StockQuantPackage(models.Model):
    _inherit = "stock.quant.package"

    # Không store để khỏi cần depends, tính lúc in label là đủ
    pack_sequence = fields.Integer(string="Package Sequence", compute="_compute_pack_seq")
    pack_total = fields.Integer(string="Total Packages", compute="_compute_pack_seq")

    def _compute_pack_seq(self):
        MoveLine = self.env['stock.move.line']
        for pack in self:
            # Tìm 1 picking chứa kiện này qua move lines (result_package_id)
            ml = MoveLine.search([('result_package_id', '=', pack.id)], limit=1)
            picking = ml.picking_id if ml else False
            if not picking:
                pack.pack_sequence = 0
                pack.pack_total = 0
                continue

            # Lấy tất cả kiện của picking (qua move lines), loại trùng và sắp theo id
            pack_ids = list({ml.result_package_id.id for ml in picking.move_line_ids if ml.result_package_id})
            pack_ids.sort()
            total = len(pack_ids)
            seq = pack_ids.index(pack.id) + 1 if pack.id in pack_ids else 0

            pack.pack_total = total
            pack.pack_sequence = seq
