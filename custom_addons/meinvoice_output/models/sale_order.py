# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ─── MEinvoice fields ─────────────────────────────────────────────────────
    meinvoice_invoiced = fields.Boolean(
        'Đã xuất HĐ MISA',
        default=False,
        copy=False,
        tracking=True,
        help='Được tự động đánh dấu khi hóa đơn liên kết được hạch toán trên meInvoice.',
    )
    meinvoice_invoiced_date = fields.Datetime(
        'Ngày xuất HĐ MISA',
        readonly=True, copy=False,
    )
    meinvoice_invoice_count = fields.Integer(
        compute='_compute_meinvoice_invoice_count',
        string='Số HĐ MISA',
    )
    meinvoice_invoice_ids = fields.One2many(
        'meinvoice.output.invoice',
        'sale_order_id',
        string='Hóa đơn điện tử MISA',
    )

    @api.depends('meinvoice_invoice_ids')
    def _compute_meinvoice_invoice_count(self):
        for rec in self:
            rec.meinvoice_invoice_count = len(rec.meinvoice_invoice_ids)

    def _meinvoice_check_invoiced(self):
        """
        Kiểm tra nếu TẤT CẢ hóa đơn liên kết đã được hạch toán
        thì đánh dấu SO là đã xuất hóa đơn MISA.
        """
        self.ensure_one()
        invoices = self.meinvoice_invoice_ids.filtered(
            lambda r: r.inv_status == '1'  # chỉ tính HĐ hợp lệ
        )
        if invoices and all(i.accounting_status == '1' for i in invoices):
            if not self.meinvoice_invoiced:
                self.write({
                    'meinvoice_invoiced':      True,
                    'meinvoice_invoiced_date': fields.Datetime.now(),
                })

    def action_view_meinvoice_invoices(self):
        """Mở danh sách hóa đơn MISA liên kết với SO này."""
        self.ensure_one()
        return {
            'name':   _('Hóa đơn điện tử MISA – %s') % self.name,
            'type':   'ir.actions.act_window',
            'res_model': 'meinvoice.output.invoice',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id},
        }
