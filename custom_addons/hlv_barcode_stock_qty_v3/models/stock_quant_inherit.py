# -*- coding: utf-8 -*-
from odoo import models, api

class StockQuant(models.Model):
    _inherit = "stock.quant"

    @api.model
    def get_qty_by_barcode_at_location(self, barcode, location_complete_name=None):
        """
        Trả tồn khả dụng (available_quantity) theo location (bao gồm cả con).
        location_complete_name ví dụ: 'TSN/Stock', 'KBC/Stock', 'KHD/Stock'
        """
        product = self.env['product.product'].search([('barcode', '=', barcode)], limit=1)
        if not product:
            return {"error": "Không tìm thấy sản phẩm có mã vạch này."}

        domain = [('product_id', '=', product.id)]

        location = None
        if location_complete_name:
            # tìm đúng complete_name để tránh trùng tên
            location = self.env['stock.location'].search(
                [('complete_name', '=', location_complete_name)], limit=1
            )
            if not location:
                # fallback: thử theo prefix 'TSN' -> lấy view location có name/prefix trùng
                prefix = (location_complete_name.split('/', 1)[0]).strip()
                location = self.env['stock.location'].search(
                    [('name', '=', prefix), ('usage', '=', 'view')], limit=1
                )
            if location:
                domain.append(('location_id', 'child_of', location.id))

        quants = self.sudo().search(domain)
        # lấy tồn khả dụng: quantity - reserved_quantity (field available_quantity)
        qty = sum(quants.mapped('available_quantity'))

        return {
            "product": product.display_name,
            "barcode": barcode,
            "qty": qty,
            "uom": product.uom_id.name,
            "location": location.complete_name if location else None,
        }
