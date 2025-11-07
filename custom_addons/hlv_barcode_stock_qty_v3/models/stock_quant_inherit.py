from odoo import models, api

class StockQuant(models.Model):
    _inherit = "stock.quant"

    @api.model
    def get_qty_by_barcode(self, barcode):
        product = self.env['product.product'].search([('barcode', '=', barcode)], limit=1)
        if not product:
            return {"error": "Không tìm thấy sản phẩm có mã vạch này."}
        quants = self.search([('product_id', '=', product.id)])
        qty = sum(quants.mapped('quantity'))
        return {
            "product": product.display_name,
            "barcode": barcode,
            "qty": qty,
            "uom": product.uom_id.name,
        }
