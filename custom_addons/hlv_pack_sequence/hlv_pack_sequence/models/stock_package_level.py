# -*- coding: utf-8 -*-
from odoo import api, fields, models

class StockPackageLevel(models.Model):
    _inherit = "stock.package.level"

    pack_sequence = fields.Integer(string="Package Sequence", compute="_compute_pack_seq", store=True)
    pack_total = fields.Integer(string="Total Packages", compute="_compute_pack_seq", store=True)

    @api.depends('picking_id', 'picking_id.package_level_ids')
    def _compute_pack_seq(self):
        # Compute numbering X/Y within each picking
        picking_map = {}
        for lvl in self:
            if lvl.picking_id:
                picking_map.setdefault(lvl.picking_id.id, lvl.picking_id)
        for picking in picking_map.values():
            levels = picking.package_level_ids.sorted('id')
            total = len(levels)
            for idx, lvl in enumerate(levels, start=1):
                lvl.pack_sequence = idx
                lvl.pack_total = total