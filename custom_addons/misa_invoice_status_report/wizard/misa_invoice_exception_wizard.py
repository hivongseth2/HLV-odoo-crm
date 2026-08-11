from odoo import fields, models


class MisaInvoiceExceptionWizard(models.TransientModel):
    _name = 'misa.invoice.exception.wizard'
    _description = 'Đánh dấu ngoại lệ xuất hóa đơn MISA'

    # Many2many (không phải Many2one) để dùng chung được cho cả nút trên form (1 phiếu) lẫn
    # bulk action trên list/dashboard (nhiều phiếu cùng lúc, cùng 1 lý do).
    picking_ids = fields.Many2many('stock.picking', string='Phiếu xuất kho', required=True)
    reason = fields.Text(string='Lý do', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.picking_ids._misa_invoice_apply_exception(self.reason)
        return {'type': 'ir.actions.act_window_close'}
