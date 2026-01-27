from odoo import models, fields, api

class ProductTemplateLabelWizard3x3(models.TransientModel):
    _name = 'product.template.label.wizard'
    _description = 'Wizard in tem sản phẩm 3x3 (35x22mm)'

    product_tmpl_ids = fields.Many2many('product.template', string='Sản phẩm', default=lambda self: self.env.context.get('active_ids'))
    print_type = fields.Selection([('barcode', 'Mã vạch'), ('qr', 'QR Code')], string='Kiểu in', default='barcode', required=True)
    qty_per_product = fields.Integer(string='Số lượng tem mỗi sản phẩm', default=1, required=True)

    def action_print_labels(self):
        return self.env.ref('product_label_3x3.action_report_product_label_3x3').report_action(self)

    def get_data_for_report(self):
        data = []
        for product in self.product_tmpl_ids:
            for _ in range(self.qty_per_product):
                data.append(product)
        return data
