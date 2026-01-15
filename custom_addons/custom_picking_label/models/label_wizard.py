from odoo import models, fields, api

class StockPickingLabelWizard(models.TransientModel):
    _name = 'stock.picking.label.wizard'
    _description = 'Wizard in tem từ phiếu kho'

    picking_id = fields.Many2one('stock.picking', string='Phiếu kho')
    print_type = fields.Selection([('barcode', 'Mã vạch'), ('qr', 'QR Code')], string='Kiểu in', default='barcode', required=True)

    line_ids = fields.One2many('stock.picking.label.wizard.line', 'wizard_id', string='Sản phẩm')

    def action_print_labels(self):
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