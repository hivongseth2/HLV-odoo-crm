from markupsafe import Markup

from odoo import fields, models


class MisaInvoiceExceptionWizard(models.TransientModel):
    _name = 'misa.invoice.exception.wizard'
    _description = 'Đánh dấu ngoại lệ xuất hóa đơn MISA'

    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho', required=True)
    reason = fields.Text(string='Lý do', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.picking_id.write({
            'misa_invoice_exception': True,
            'misa_invoice_exception_reason': self.reason,
            'misa_invoice_exception_by_id': self.env.user.id,
            'misa_invoice_exception_date': fields.Datetime.now(),
        })
        self.picking_id.message_post(
            body=Markup("<b>Đã đánh dấu ngoại lệ xuất hóa đơn MISA.</b><br/>Lý do: %s") % self.reason
        )
        return {'type': 'ir.actions.act_window_close'}
