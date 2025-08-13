
# -*- coding: utf-8 -*-
from odoo import api, fields, models

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def barcode_autosave_create_lines(self, payload_lines):
        self.ensure_one()
        self.check_access_rights('write')
        self.check_access_rule('write')

        results = []
        for line in payload_lines or []:
            qty = float(line.get('qty_done') or 0.0)
            if not qty:
                continue

            move = None
            move_id = line.get('move_id')
            if move_id:
                move = self.env['stock.move'].browse(move_id).exists()

            product_id = line.get('product_id')
            if not move:
                if not product_id:
                    continue
                move = self.move_ids_without_package.filtered(
                    lambda m: m.product_id.id == product_id and m.state not in ('done', 'cancel')
                )[:1]

            if not move:
                if not product_id:
                    continue
                product = self.env['product.product'].browse(product_id).exists()
                if not product:
                    continue
                move = self.env['stock.move'].create({
                    'name': product.display_name,
                    'picking_id': self.id,
                    'product_id': product.id,
                    'product_uom': product.uom_id.id,
                    'location_id': self.location_id.id,
                    'location_dest_id': self.location_dest_id.id,
                    'product_uom_qty': 0.0,
                })

            vals = {
                'picking_id': self.id,
                'move_id': move.id,
                'product_id': move.product_id.id,
                'qty_done': qty,
                'product_uom_id': line.get('uom_id') or move.product_uom.id,
                'location_id': line.get('location_id') or move.location_id.id,
                'location_dest_id': line.get('location_dest_id') or move.location_dest_id.id,
            }
            for opt in ('lot_id', 'package_id', 'result_package_id'):
                if line.get(opt):
                    vals[opt] = line[opt]

            sml = self.env['stock.move.line'].create(vals)
            results.append({
                'client_key': line.get('client_key'),
                'line_id': sml.id,
                'qty_done': sml.qty_done,
            })
        return results
