# -*- coding: utf-8 -*-
import logging
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmisPaymentRequest(models.Model):
    _name = 'amis.payment.request'
    _description = 'Đề nghị chi tiền nhà cung cấp MISA'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Số đề nghị', default='/', required=True, copy=False, index=True)
    purchase_order_id = fields.Many2one(
        'purchase.order', string='Đơn mua hàng', required=True, ondelete='cascade', index=True,
    )
    partner_id = fields.Many2one('res.partner', string='Nhà cung cấp', required=True, index=True)
    company_id = fields.Many2one('res.company', string='Công ty', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Tiền tệ', required=True)
    amount = fields.Monetary(string='Số tiền đề nghị chi', required=True)
    payment_date = fields.Date(string='Ngày đề nghị chi', required=True, default=fields.Date.context_today)
    memo = fields.Text(string='Diễn giải')

    company_bank_id = fields.Many2one('res.partner.bank', string='Tài khoản chi')
    company_bank_account_number = fields.Char(string='Số tài khoản chi')
    company_bank_name = fields.Char(string='Ngân hàng chi')

    vendor_bank_id = fields.Many2one('res.partner.bank', string='Tài khoản nhận của NCC')
    vendor_bank_account_number = fields.Char(string='Số tài khoản nhận')
    vendor_bank_name = fields.Char(string='Ngân hàng nhận')
    vendor_bank_branch = fields.Char(string='Chi nhánh ngân hàng nhận')
    vendor_account_holder = fields.Char(string='Tên chủ tài khoản')

    debit_account = fields.Char(string='TK Nợ', default='331')
    credit_account = fields.Char(string='TK Có', default='1121')

    org_refid = fields.Char(string='MISA org_refid', copy=False, index=True)
    misa_refid = fields.Char(string='MISA refid', copy=False, index=True)
    job_id = fields.Many2one('amis.sync.job', string='Job đồng bộ MISA', readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('pending', 'Chờ đồng bộ'),
        ('sent', 'Đã gửi MISA'),
        ('synced', 'MISA thành công'),
        ('error', 'Lỗi'),
    ], string='Trạng thái', default='draft', index=True)
    error_msg = fields.Text(string='Lỗi MISA')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('amis.payment.request') or '/'
        return super().create(vals_list)

    def action_enqueue_sync(self):
        for request in self:
            request._enqueue_sync_job()
        return True

    def action_run_sync(self):
        for request in self:
            request._enqueue_sync_job()
            if request.job_id:
                request.job_id.action_run_now()
        return True

    def action_open_purchase_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Đơn mua hàng',
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'res_id': self.purchase_order_id.id,
            'target': 'current',
        }

    def _enqueue_sync_job(self):
        self.ensure_one()
        existing = self.env['amis.sync.job'].sudo().search([
            ('payment_request_id', '=', self.id),
            ('direction', '=', 'payment_request'),
            ('status', 'in', ('pending', 'error')),
        ], limit=1)
        if existing:
            self.write({'job_id': existing.id, 'state': 'pending'})
            return existing
        job = self.env['amis.sync.job'].sudo().create({
            'payment_request_id': self.id,
            'purchase_order_id': self.purchase_order_id.id,
            'direction': 'payment_request',
        })
        self.write({'job_id': job.id, 'state': 'pending', 'error_msg': False})
        return job

    def _sync_payment_request_to_misa(self):
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        config.ensure_sync_ready()
        voucher_payload = self._prepare_misa_payment_request_payload(config)
        config.push_payment_request(voucher_payload)
        self.sudo().write({
            'org_refid': voucher_payload.get('org_refid') or '',
            'state': 'sent',
            'error_msg': False,
        })

    def _prepare_misa_payment_request_payload(self, config):
        self.ensure_one()
        if not self.partner_id:
            raise UserError('Đề nghị chi thiếu nhà cung cấp.')
        if not self.amount or self.amount <= 0:
            raise UserError('Số tiền đề nghị chi phải lớn hơn 0.')
        branch_id = (config.misa_branch_id or '').strip()
        if not branch_id:
            raise UserError('Chưa cấu hình MISA Branch ID.')

        po = self.purchase_order_id
        dictionary_items = []
        account_object = po._ensure_misa_account_object(config, self.partner_id, dictionary_items)
        if dictionary_items:
            config.push_dictionary(dictionary_items)
            config.clear_dictionary_cache([1])

        org_refid = (self.org_refid or '').strip()
        if not org_refid:
            org_refid = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_payment_request|%d' % self.id))
            self.sudo().write({'org_refid': org_refid})

        refdate = self._misa_datetime(self.payment_date)
        amount = float(self.amount or 0.0)
        memo = (self.memo or '').strip() or 'Đề nghị chi tiền nhà cung cấp %s theo đơn mua %s' % (
            self.partner_id.display_name,
            po.name,
        )
        currency = self.currency_id.name or 'VND'
        exchange_rate = float(getattr(po, 'currency_rate', 1.0) or 1.0)
        account_object_id = account_object.get('account_object_id') or ''
        account_object_code = account_object.get('account_object_code') or ''
        account_object_name = account_object.get('account_object_name') or self.partner_id.display_name

        detail_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_payment_request_detail|%d' % self.id))
        return {
            'voucher_type': 3,
            'org_refid': org_refid,
            'org_refno': self.name,
            'org_reftype': 1510,
            'org_reftype_name': 'Ủy nhiệm chi',
            'refid': org_refid,
            'refno': self.name,
            'reftype': 1510,
            'act_voucher_type': 0,
            'branch_id': branch_id,
            'refdate': refdate,
            'posted_date': refdate,
            'account_object_id': account_object_id,
            'account_object_code': account_object_code,
            'account_object_name': account_object_name,
            'account_object_address': self.partner_id.contact_address_complete or '',
            'account_object_bank_account': self.vendor_bank_account_number or '',
            'account_object_bank_name': self.vendor_bank_name or '',
            'account_object_bank_branch_name': self.vendor_bank_branch or '',
            'bank_account_number': self.company_bank_account_number or '',
            'bank_name': self.company_bank_name or '',
            'currency_id': currency,
            'exchange_rate': exchange_rate,
            'journal_memo': memo,
            'total_amount_oc': amount,
            'total_amount': amount,
            'total_amount_finance': amount,
            'total_amount_management': amount,
            'is_get_new_id': False,
            'auto_refno': False,
            'state': 0,
            'detail': [{
                'ref_detail_id': detail_id,
                'refid': org_refid,
                'sort_order': 1,
                'description': memo,
                'debit_account': self.debit_account or '331',
                'credit_account': self.credit_account or '1121',
                'account_object_id': account_object_id,
                'account_object_code': account_object_code,
                'account_object_name': account_object_name,
                'amount_oc': amount,
                'amount': amount,
                'amount_finance': amount,
                'amount_management': amount,
                'currency_id': currency,
                'exchange_rate': exchange_rate,
                'state': 0,
            }],
        }

    def _misa_datetime(self, value):
        if not value:
            value = fields.Date.context_today(self)
        date_value = fields.Date.to_date(value)
        return '%sT00:00:00+07:00' % date_value.isoformat()


class PurchaseOrderAmisPaymentRequest(models.Model):
    _inherit = 'purchase.order'

    misa_payment_request_ids = fields.One2many(
        'amis.payment.request', 'purchase_order_id', string='Đề nghị chi MISA',
    )
    misa_payment_request_count = fields.Integer(
        string='Số đề nghị chi MISA', compute='_compute_misa_payment_request_count',
    )

    @api.depends('misa_payment_request_ids')
    def _compute_misa_payment_request_count(self):
        for order in self:
            order.misa_payment_request_count = len(order.misa_payment_request_ids)

    def action_open_misa_payment_request_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lập đề nghị chi tiền nhà cung cấp',
            'res_model': 'amis.payment.request.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_purchase_order_id': self.id,
            },
        }

    def action_view_misa_payment_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Đề nghị chi MISA',
            'res_model': 'amis.payment.request',
            'view_mode': 'list,form',
            'domain': [('purchase_order_id', '=', self.id)],
            'context': {
                'default_purchase_order_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_currency_id': self.currency_id.id,
            },
        }
