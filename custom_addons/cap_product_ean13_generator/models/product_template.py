from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_barcode = fields.Boolean(related='product_variant_ids.is_barcode', string='Kiểm tra cài đặt mã vạch', readonly=False)
    image_product = fields.Binary(related='product_variant_ids.image_product', string='Hình ảnh mã vạch', readonly=False)
