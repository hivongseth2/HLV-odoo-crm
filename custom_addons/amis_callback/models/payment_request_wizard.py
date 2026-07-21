# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class AmisPaymentRequestWizard(models.TransientModel):
    _name = 'amis.payment.request.wizard'
    _description = 'Wizard lập đề nghị chi tiền nhà cung cấp MISA'

    purchase_order_id = fields.Many2one('purchase.order', string='Đơn mua hàng', required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string='Nhà cung cấp', required=True, readonly=True)
    company_id = fields.Many2one('res.company', string='Công ty', required=True, readonly=True)
    currency_id = fields.Many2one('res.currency', string='Tiền tệ', required=True, readonly=True)
    amount = fields.Monetary(string='Số tiền đề nghị chi', required=True)
    payment_date = fields.Date(string='Ngày đề nghị chi', required=True, default=fields.Date.context_today)
    memo = fields.Text(string='Diễn giải')

    payment_method = fields.Selection([
        ('cash', 'Tiền mặt'),
        ('bank', 'Tiền gửi'),
    ], string='Phương thức chi', required=True, default='bank')
    company_partner_id = fields.Many2one(
        related='company_id.partner_id', string='Đối tác công ty', readonly=True,
    )
    company_bank_id = fields.Many2one(
        'res.partner.bank', string='Tài khoản chi', readonly=True,
    )
    company_bank_account_number = fields.Char(string='Số tài khoản chi')
    company_bank_name = fields.Char(string='Ngân hàng chi')

    vendor_bank_id = fields.Many2one('res.partner.bank', string='Tài khoản nhận của NCC')
    vendor_bank_account_number = fields.Char(string='Số tài khoản nhận')
    vendor_bank_name = fields.Char(string='Ngân hàng nhận')
    vendor_bank_branch = fields.Char(string='Chi nhánh ngân hàng nhận')
    vendor_account_holder = fields.Char(string='Tên chủ tài khoản')

    beneficiary_account_type = fields.Selection([
        ('company', 'Tài khoản công ty'),
        ('personal', 'Tài khoản cá nhân'),
    ], string='Loại tài khoản nhận')

    debit_account = fields.Char(string='TK Nợ', default='331')
    credit_account = fields.Char(string='TK Có', default='1121')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        po_id = self.env.context.get('default_purchase_order_id') or self.env.context.get('active_id')
        if not po_id:
            return vals
        po = self.env['purchase.order'].browse(po_id).exists()
        if not po:
            return vals
        partner = po.partner_id.commercial_partner_id or po.partner_id
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        bank_config = config.payment_bank_config_ids.filtered(
            lambda line: line.active
            and line.purpose == 'purchase'
            and line.company_id == po.company_id
        )[:1]
        company_bank = bank_config.company_bank_id if bank_config else self._first_bank(po.company_id.partner_id)
        vendor_bank = self._first_bank(partner)
        vals.update({
            'purchase_order_id': po.id,
            'partner_id': partner.id,
            'company_id': po.company_id.id,
            'currency_id': po.currency_id.id,
            'amount': po.amount_total,
            'payment_date': fields.Date.context_today(self),
            'payment_method': 'bank',
            'memo': 'Đề nghị chi tiền nhà cung cấp %s theo đơn mua %s' % (partner.display_name, po.name),
            'company_bank_id': company_bank.id if company_bank else False,
            'vendor_bank_id': vendor_bank.id if vendor_bank else False,
            'debit_account': bank_config.debit_account if bank_config else '331',
            'credit_account': bank_config.credit_account if bank_config else '1121',
        })
        vals.update(self._bank_vals(company_bank, prefix='company'))
        vals.update(self._bank_vals(vendor_bank, prefix='vendor'))
        if vendor_bank and 'acc_holder_name' in vendor_bank._fields and vendor_bank.acc_holder_name:
            vals['vendor_account_holder'] = vendor_bank.acc_holder_name
        else:
            vals['vendor_account_holder'] = partner.display_name
        return vals

    def _first_bank(self, partner):
        if not partner or 'bank_ids' not in partner._fields:
            return self.env['res.partner.bank']
        return partner.bank_ids[:1]

    def _bank_vals(self, bank, prefix):
        vals = {}
        if not bank:
            return vals
        bank_name = bank.bank_id.name if bank.bank_id else ''
        if prefix == 'company':
            vals['company_bank_account_number'] = bank.acc_number or ''
            vals['company_bank_name'] = bank_name
        else:
            vals['vendor_bank_account_number'] = bank.acc_number or ''
            vals['vendor_bank_name'] = bank_name
            vals['vendor_bank_branch'] = bank.bank_id.street if bank.bank_id and 'street' in bank.bank_id._fields else ''
        return vals

    @api.onchange('company_bank_id')
    def _onchange_company_bank_id(self):
        for wizard in self:
            vals = wizard._bank_vals(wizard.company_bank_id, prefix='company')
            wizard.company_bank_account_number = vals.get('company_bank_account_number', '')
            wizard.company_bank_name = vals.get('company_bank_name', '')

    @api.onchange('payment_method')
    def _onchange_payment_method(self):
        for wizard in self:
            if wizard.payment_method == 'cash':
                wizard.credit_account = '1111'
                continue
            config = self.env['amis.callback.config'].sudo().ensure_singleton()
            bank_config = config.payment_bank_config_ids.filtered(
                lambda line: line.active
                and line.purpose == 'purchase'
                and line.company_id == wizard.company_id
            )[:1]
            wizard.credit_account = bank_config.credit_account if bank_config else '1121'
            if bank_config and bank_config.company_bank_id:
                wizard.company_bank_id = bank_config.company_bank_id
                vals = wizard._bank_vals(bank_config.company_bank_id, prefix='company')
                wizard.company_bank_account_number = vals.get('company_bank_account_number', '')
                wizard.company_bank_name = vals.get('company_bank_name', '')

    @api.onchange('vendor_bank_id')
    def _onchange_vendor_bank_id(self):
        for wizard in self:
            vals = wizard._bank_vals(wizard.vendor_bank_id, prefix='vendor')
            wizard.vendor_bank_account_number = vals.get('vendor_bank_account_number', '')
            wizard.vendor_bank_name = vals.get('vendor_bank_name', '')
            wizard.vendor_bank_branch = vals.get('vendor_bank_branch', '')
            if wizard.vendor_bank_id and 'acc_holder_name' in wizard.vendor_bank_id._fields and wizard.vendor_bank_id.acc_holder_name:
                wizard.vendor_account_holder = wizard.vendor_bank_id.acc_holder_name
            else:
                wizard.vendor_account_holder = wizard.partner_id.display_name or ''

    def action_create_payment_request(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError('Số tiền đề nghị chi phải lớn hơn 0.')
        if self.payment_method == 'bank':
            if not self.company_bank_id or not self.company_bank_account_number:
                raise UserError('Vui lòng chọn tài khoản chi của công ty.')
            if self.vendor_bank_id and self.vendor_bank_id.partner_id != self.partner_id:
                raise UserError('Tài khoản nhận phải thuộc nhà cung cấp của đơn mua hàng.')
            if not self.beneficiary_account_type:
                raise UserError('Vui lòng chọn tài khoản nhận là tài khoản công ty hay cá nhân.')
            if not self.vendor_bank_account_number or not self.vendor_bank_name:
                raise UserError('Vui lòng nhập số tài khoản và ngân hàng nhận.')
            if not (self.vendor_account_holder or '').strip():
                raise UserError('Vui lòng nhập tên chủ tài khoản nhận.')
        request = self.env['amis.payment.request'].create({
            'purchase_order_id': self.purchase_order_id.id,
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'amount': self.amount,
            'payment_date': self.payment_date,
            'memo': self.memo,
            'payment_method': self.payment_method,
            'company_bank_id': self.company_bank_id.id,
            'company_bank_account_number': self.company_bank_account_number,
            'company_bank_name': self.company_bank_name,
            'vendor_bank_id': self.vendor_bank_id.id,
            'vendor_bank_account_number': self.vendor_bank_account_number,
            'vendor_bank_name': self.vendor_bank_name,
            'vendor_bank_branch': self.vendor_bank_branch,
            'vendor_account_holder': self.vendor_account_holder,
            'beneficiary_account_type': self.beneficiary_account_type,
            'debit_account': self.debit_account,
            'credit_account': self.credit_account,
        })
        request.action_enqueue_sync()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Đề nghị chi MISA',
            'res_model': 'amis.payment.request',
            'view_mode': 'form',
            'res_id': request.id,
            'target': 'current',
        }
