from io import BytesIO

from barcode.ean import EAN13

from odoo import models, api,fields, _

from datetime import datetime
import math
# from barcode import generate

import random
# from barcode.writer import ImageWriter
import base64
import os

import barcode
from barcode.writer import ImageWriter



class ProductProduct(models.Model):
    _inherit = "product.product"

    is_barcode = fields.Boolean('Check Barcode Setting')
    image_product = fields.Binary('Barcode Image')

    @api.model
    def default_get(self,field_lst):
        res = super(ProductProduct, self).default_get(field_lst)
        if not self.env['res.config.settings'].search([], limit=1, order="id desc").barcode_generate:
            res['is_barcode'] = True
        return res

    @api.model
    def create(self, vals):
        res = super(ProductProduct, self).create(vals)
        if not vals.get('barcode') and self.env['res.config.settings'].sudo().search([], limit=1,
                                                                                     order="id desc").barcode_generate:
            if self.env['res.config.settings'].search([], limit=1, order="id desc").option_generated == 'date':
                barcode_str = self.env['barcode.nomenclature'].sanitize_ean(
                    "%s%s" % (res.id, datetime.now().strftime("%d%m%y%H%M")))
            else:
                number_random = int("%0.13d" % random.randint(0, 999999999999))
                barcode_str = self.env['barcode.nomenclature'].sanitize_ean("%s" % (number_random))
            # Create a barcode image
            ean = EAN13(barcode_str, writer=ImageWriter())
            image = ean.render()
            # Convert the image to base64
            image_buffer = BytesIO()
            image.save(image_buffer, format="PNG")
            res.barcode = barcode_str
            image_data = base64.b64encode(image_buffer.getvalue()).decode('utf-8')
            res.image_product = image_data
        return res



