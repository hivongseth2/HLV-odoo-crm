from datetime import datetime
import random
from odoo import models, fields, api

class StockPickingLabelWizard(models.TransientModel):
    _name = 'stock.picking.label.wizard'
    _description = 'Wizard in tem từ phiếu kho'

    picking_id = fields.Many2one('stock.picking', string='Phiếu kho')
    print_type = fields.Selection([('barcode', 'Mã vạch'), ('qr', 'QR Code')], string='Kiểu in', default='barcode', required=True)
    
    auto_generate_ean13 = fields.Boolean(string="Tự động tạo mã vạch", help="Tự động tạo mã EAN13 cho sản phẩm chưa có mã")
    generate_type = fields.Selection([
        ('date', 'Theo ngày hiện tại'),
        ('random', 'Ngẫu nhiên')
    ], string="Kiểu tạo mã", default='date')

    line_ids = fields.One2many('stock.picking.label.wizard.line', 'wizard_id', string='Sản phẩm')

    def action_print_labels(self):
        # Auto generate barcodes if enabled
        if self.auto_generate_ean13:
            for line in self.line_ids:
                product = line.product_id
                if not product.barcode:
                    barcode_str = False
                    if self.generate_type == 'date':
                        barcode_str = self.env["barcode.nomenclature"].sanitize_ean(
                            "%s%s" % (product.id, datetime.now().strftime("%d%m%y%H%M"))
                        )
                    else:
                        number_random = int("%0.13d" % random.randint(0, 999999999999))
                        barcode_str = self.env["barcode.nomenclature"].sanitize_ean(
                            "%s" % (number_random)
                        )
                    
                    if barcode_str:
                         product.write({"barcode": barcode_str})

        # Gọi hành động in report
        return self.env.ref('custom_picking_label.action_report_custom_label').report_action(self)

    def get_data_for_report(self):
        # Hàm này sẽ được gọi từ QWeb để lặp lại số lượng tem
        # Ví dụ: Sản phẩm A có qty_to_print = 3 -> Tạo ra list [A, A, A]
        data = []
        for line in self.line_ids:
            for _ in range(line.qty_to_print):
                data.append(line.product_id)
        return data

class StockPickingLabelWizardLine(models.TransientModel):
    _name = 'stock.picking.label.wizard.line'
    _description = 'Chi tiết dòng in tem'

    wizard_id = fields.Many2one('stock.picking.label.wizard')
    product_id = fields.Many2one('product.product', string='Sản phẩm', required=True)
    qty_to_print = fields.Integer(string='SL Tem', default=1)