# -*- coding: utf-8 -*-
from odoo import api, fields, models

class StockQuantPackage(models.Model):
    _inherit = "stock.quant.package"

    pack_sequence = fields.Integer(string="Package Sequence", compute="_compute_pack_seq", store=True)
    pack_total = fields.Integer(string="Total Packages", compute="_compute_pack_seq", store=True)

    @api.depends('picking_ids', 'picking_ids.package_ids')
    def _compute_pack_seq(self):
        for pack in self:
            if pack.picking_ids:
                # lấy phiếu đầu tiên (đa số 1 kiện = 1 picking)
                picking = pack.picking_ids[0]
                all_packs = picking.package_ids.sorted("id")
                total = len(all_packs)
                for idx, p in enumerate(all_packs, start=1):
                    p.pack_sequence = idx
                    p.pack_total = total
