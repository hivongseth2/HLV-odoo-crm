# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


LOCAL_UTC_OFFSET_HOURS = 7


class ShopeeMeinvoiceReconcileWizard(models.TransientModel):
    _name = 'shopee.meinvoice.reconcile.wizard'
    _description = 'Đối chiếu đơn Shopee và hóa đơn điện tử'

    date_start = fields.Date(
        string='Ngày bắt đầu',
        required=True,
        default=lambda self: fields.Date.context_today(self),
    )
    date_end = fields.Date(
        string='Ngày kết thúc',
        required=True,
        default=lambda self: fields.Date.context_today(self),
    )
    tolerance = fields.Float(
        string='Sai lệch cho phép',
        default=1.0,
        help='Đơn vị VND. Dùng để bỏ qua sai lệch làm tròn rất nhỏ.',
    )
    limit = fields.Integer(
        string='Giới hạn dòng',
        default=200,
        help='Để trống hoặc nhập 0 nếu muốn quét toàn bộ khoảng ngày.',
    )
    show_ok = fields.Boolean(string='Hiển thị dòng khớp', default=True)
    line_ids = fields.One2many(
        'shopee.meinvoice.reconcile.wizard.line',
        'wizard_id',
        string='Kết quả',
        readonly=True,
    )
    total_order_count = fields.Integer(string='Tổng đơn Shopee', readonly=True)
    ok_count = fields.Integer(string='Khớp', readonly=True)
    missing_invoice_count = fields.Integer(string='Chưa có HĐĐT', readonly=True)
    amount_mismatch_count = fields.Integer(string='Lệch tiền', readonly=True)
    multiple_invoice_count = fields.Integer(string='Nhiều HĐĐT', readonly=True)
    result_summary = fields.Text(string='Tổng kết', readonly=True)

    def _local_date_domain_utc(self):
        self.ensure_one()
        if self.date_end < self.date_start:
            raise UserError('Ngày kết thúc phải lớn hơn hoặc bằng ngày bắt đầu.')

        start_local = datetime.combine(self.date_start, time.min)
        end_exclusive_local = datetime.combine(self.date_end + timedelta(days=1), time.min)
        offset = timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
        return (
            fields.Datetime.to_string(start_local - offset),
            fields.Datetime.to_string(end_exclusive_local - offset),
        )

    @api.model
    def _invoice_total(self, invoices):
        return sum(invoices.mapped('total_amount_oc')) if invoices else 0.0

    def action_reconcile(self):
        self.ensure_one()

        date_from_utc, date_to_utc = self._local_date_domain_utc()
        domain = [
            ('shopee_order_ref', '!=', False),
            ('shopee_order_ref', '!=', ''),
            ('date_order', '>=', date_from_utc),
            ('date_order', '<', date_to_utc),
        ]

        SaleOrder = self.env['sale.order'].sudo()
        Invoice = self.env['meinvoice.invoice'].sudo()
        orders = SaleOrder.search(
            domain,
            order='date_order asc, id asc',
            limit=max(self.limit or 0, 0),
        )

        commands = [(5, 0, 0)]
        counters = {
            'ok': 0,
            'missing_invoice': 0,
            'amount_mismatch': 0,
            'multiple_invoice': 0,
        }

        for order in orders:
            invoices = Invoice.search([
                ('sale_order_id', '=', order.id),
                ('state', '!=', 'cancelled'),
            ], order='create_date asc, id asc')

            invoice_count = len(invoices)
            invoice_total = self._invoice_total(invoices)
            order_total = float(order.amount_total or 0.0)
            amount_delta = round(invoice_total - order_total, 2)

            if not invoices:
                status = 'missing_invoice'
            elif invoice_count != 1:
                status = 'multiple_invoice'
            elif abs(amount_delta) > float(self.tolerance or 0.0):
                status = 'amount_mismatch'
            else:
                status = 'ok'

            counters[status] += 1
            if status == 'ok' and not self.show_ok:
                continue

            commands.append((0, 0, {
                'sale_order_id': order.id,
                'order_date': order.date_order,
                'shopee_order_ref': order.shopee_order_ref,
                'partner_id': order.partner_id.id,
                'currency_id': order.currency_id.id,
                'order_total': order_total,
                'invoice_ids': [(6, 0, invoices.ids)],
                'invoice_count': invoice_count,
                'invoice_total': invoice_total,
                'amount_delta': amount_delta,
                'status': status,
            }))

        summary = [
            'Khoảng ngày local UTC+7: %s -> %s' % (self.date_start, self.date_end),
            'Domain UTC trên date_order: >= %s và < %s' % (date_from_utc, date_to_utc),
            'Tổng đơn Shopee quét: %s' % len(orders),
            'Khớp: %s' % counters['ok'],
            'Chưa có HĐĐT: %s' % counters['missing_invoice'],
            'Lệch tiền: %s' % counters['amount_mismatch'],
            'Nhiều HĐĐT chưa hủy: %s' % counters['multiple_invoice'],
            'Cột tổng tiền hóa đơn: meinvoice.invoice.total_amount_oc',
        ]

        self.write({
            'line_ids': commands,
            'total_order_count': len(orders),
            'ok_count': counters['ok'],
            'missing_invoice_count': counters['missing_invoice'],
            'amount_mismatch_count': counters['amount_mismatch'],
            'multiple_invoice_count': counters['multiple_invoice'],
            'result_summary': '\n'.join(summary),
        })

        return {
            'type': 'ir.actions.act_window',
            'name': 'Đối chiếu HĐĐT Shopee',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }


class ShopeeMeinvoiceReconcileWizardLine(models.TransientModel):
    _name = 'shopee.meinvoice.reconcile.wizard.line'
    _description = 'Dòng đối chiếu đơn Shopee và hóa đơn điện tử'
    _order = 'order_date asc, id asc'

    wizard_id = fields.Many2one(
        'shopee.meinvoice.reconcile.wizard',
        required=True,
        ondelete='cascade',
    )
    sale_order_id = fields.Many2one('sale.order', string='Đơn hàng', readonly=True)
    order_date = fields.Datetime(string='Ngày đơn', readonly=True)
    shopee_order_ref = fields.Char(string='Tham chiếu Shopee', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Khách hàng', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Tiền tệ', readonly=True)
    order_total = fields.Monetary(
        string='Tổng tiền đơn hàng',
        currency_field='currency_id',
        readonly=True,
    )
    invoice_ids = fields.Many2many(
        'meinvoice.invoice',
        string='Hóa đơn điện tử',
        readonly=True,
    )
    invoice_count = fields.Integer(string='Số HĐĐT', readonly=True)
    invoice_total = fields.Monetary(
        string='Tổng tiền xuất hóa đơn',
        currency_field='currency_id',
        readonly=True,
        help='Tổng từ meinvoice.invoice.total_amount_oc, bỏ qua hóa đơn đã hủy.',
    )
    amount_delta = fields.Monetary(
        string='Chênh lệch',
        currency_field='currency_id',
        readonly=True,
    )
    status = fields.Selection(
        [
            ('ok', 'Khớp'),
            ('missing_invoice', 'Chưa có HĐĐT'),
            ('amount_mismatch', 'Lệch tiền'),
            ('multiple_invoice', 'Nhiều HĐĐT'),
        ],
        string='Trạng thái',
        readonly=True,
    )

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.sale_order_id.display_name,
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_invoices(self):
        self.ensure_one()
        if not self.invoice_ids:
            raise UserError('Dòng này chưa có hóa đơn điện tử chưa hủy.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hóa đơn điện tử',
            'res_model': 'meinvoice.invoice',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
            'target': 'current',
        }
