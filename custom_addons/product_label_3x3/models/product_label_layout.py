from odoo import fields, models

class ProductLabelLayout(models.TransientModel):
    _inherit = 'product.label.layout'

    print_format = fields.Selection(selection_add=[
        ('3x3_35x22', '3 x 3 (35x22mm)')
    ], ondelete={'3x3_35x22': 'set default'})

    print_type = fields.Selection([
        ('barcode', 'Mã vạch'), 
        ('qr', 'QR Code')
    ], string='Kiểu in', default='barcode')

    def _prepare_report_data(self):
        xml_id, data = super()._prepare_report_data()

        if self.print_format == '3x3_35x22':
            xml_id = 'product_label_3x3.report_product_label_3x3'
            
            # Prepare explicit list of products to print
            product_tmpl_ids = []
            product_variant_ids = []
            
            if self.custom_quantity:
                # Custom quantity for all selected products
                for product in self.product_tmpl_ids:
                    product_tmpl_ids.extend([product.id] * self.custom_quantity)
                for product in self.product_ids:
                    product_variant_ids.extend([product.id] * self.custom_quantity)
            else:
                 # Standard quantity logic (1 per product)
                for product in self.product_tmpl_ids:
                     product_tmpl_ids.append(product.id)
                for product in self.product_ids:
                     product_variant_ids.append(product.id)

            data.update({
                'print_type': self.print_type,
                'product_tmpl_ids': product_tmpl_ids,
                'product_variant_ids': product_variant_ids,
            })
        
        return xml_id, data
