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
            data.update({
                'print_type': self.print_type,
            })
        
        return xml_id, data
