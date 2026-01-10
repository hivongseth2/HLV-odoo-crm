from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_barcode = fields.Boolean(related='product_variant_ids.is_barcode', string='Check Barcode Setting', readonly=False)
    image_product = fields.Binary(related='product_variant_ids.image_product', string='Barcode Image', readonly=False)
