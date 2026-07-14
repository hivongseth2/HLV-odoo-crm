# -*- coding: utf-8 -*-
import logging
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmisPaymentBankConfig(models.Model):
    _name = 'amis.payment.bank.config'
    _description = 'Cấu hình tài khoản chi theo mục đích MISA'
    _order = 'company_id, purpose'

    config_id = fields.Many2one(
        'amis.callback.config', string='Cấu hình AMIS', required=True, ondelete='cascade', index=True,
    )
    purpose = fields.Selection([
        ('purchase', 'Chi mua hàng'),
        ('loyalty', 'Chi đổi điểm Loyalty'),
    ], string='Mục đích chi', required=True, default='purchase', index=True)
    company_id = fields.Many2one(
        'res.company', string='Công ty', required=True, default=lambda self: self.env.company,
    )
    company_partner_id = fields.Many2one(
        related='company_id.partner_id', string='Đối tác công ty', readonly=True,
    )
    company_bank_id = fields.Many2one(
        'res.partner.bank', string='Tài khoản chi mặc định', required=True,
    )
    debit_account = fields.Char(string='TK Nợ mặc định', default='331', required=True)
    credit_account = fields.Char(string='TK Có mặc định', default='1121', required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            'config_purpose_company_unique',
            'unique(config_id, purpose, company_id)',
            'Mỗi công ty chỉ được cấu hình một tài khoản chi cho mỗi mục đích.',
        ),
    ]

    @api.constrains('company_id', 'company_bank_id')
    def _check_company_bank_owner(self):
        for record in self:
            if (
                record.company_bank_id
                and record.company_bank_id.partner_id != record.company_id.partner_id
            ):
                raise ValidationError('Tài khoản chi mặc định phải thuộc đúng công ty đã chọn.')


class AmisCallbackConfigPaymentBank(models.Model):
    _inherit = 'amis.callback.config'

    payment_bank_config_ids = fields.One2many(
        'amis.payment.bank.config', 'config_id', string='Tài khoản chi theo mục đích',
    )


class AmisPaymentRequest(models.Model):
    _name = 'amis.payment.request'
    _description = 'Đề nghị chi tiền MISA'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Số đề nghị', default='/', required=True, copy=False, index=True)
    purchase_order_id = fields.Many2one(
        'purchase.order', string='Đơn mua hàng', ondelete='cascade', index=True,
    )
    loyalty_reward_request_id = fields.Many2one(
        'hlv.loyalty.reward.request', string='Yêu cầu đổi điểm',
        ondelete='cascade', index=True, copy=False,
    )
    partner_id = fields.Many2one('res.partner', string='Người nhận', required=True, index=True)
    company_id = fields.Many2one('res.company', string='Công ty', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Tiền tệ', required=True)
    amount = fields.Monetary(string='Số tiền đề nghị chi', required=True)
    payment_date = fields.Date(string='Ngày đề nghị chi', required=True, default=fields.Date.context_today)
    memo = fields.Text(string='Diễn giải')

    payment_method = fields.Selection([
        ('cash', 'Tiền mặt'),
        ('bank', 'Tiền gửi'),
    ], string='Phương thức chi', required=True, default='bank', index=True)

    company_bank_id = fields.Many2one('res.partner.bank', string='Tài khoản chi')
    company_bank_account_number = fields.Char(string='Số tài khoản chi')
    company_bank_name = fields.Char(string='Ngân hàng chi')

    vendor_bank_id = fields.Many2one('res.partner.bank', string='Tài khoản nhận')
    vendor_bank_account_number = fields.Char(string='Số tài khoản nhận')
    vendor_bank_name = fields.Char(string='Ngân hàng nhận')
    vendor_bank_branch = fields.Char(string='Chi nhánh ngân hàng nhận')
    vendor_account_holder = fields.Char(string='Tên chủ tài khoản')

    beneficiary_account_type = fields.Selection([
        ('company', 'Tài khoản công ty'),
        ('personal', 'Tài khoản cá nhân'),
    ], string='Loại tài khoản nhận', copy=False)

    debit_account = fields.Char(string='TK Nợ', default='331')
    credit_account = fields.Char(string='TK Có', default='1121')

    org_refid = fields.Char(string='MISA org_refid', copy=False, index=True)
    misa_refid = fields.Char(string='MISA refid', copy=False, index=True)
    job_id = fields.Many2one('amis.sync.job', string='Job đồng bộ MISA', readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('pending', 'Chờ đồng bộ'),
        ('sent', 'Đã gửi MISA'),
        ('request_accepted', 'MISA đã nhận đề nghị'),
        ('synced', 'MISA thành công'),
        ('delete_pending', 'Đang thu hồi'),
        ('manual_delete_required', 'Chờ xóa chứng từ trên MISA'),
        ('deleted', 'Đã thu hồi'),
        ('error', 'Lỗi'),
    ], string='Trạng thái', default='draft', index=True)
    error_msg = fields.Text(string='Lỗi MISA')
    callback_session_id = fields.Char(string='MISA Session ID', copy=False)
    state_updated_at = fields.Datetime(string='Cập nhật trạng thái MISA lúc', copy=False)

    _sql_constraints = [
        (
            'loyalty_reward_request_unique',
            'unique(loyalty_reward_request_id)',
            'Mỗi yêu cầu đổi điểm chỉ được tạo một đề nghị chi MISA.',
        ),
    ]

    @api.constrains('purchase_order_id', 'loyalty_reward_request_id')
    def _check_source_document(self):
        for request in self:
            if bool(request.purchase_order_id) == bool(request.loyalty_reward_request_id):
                raise ValidationError(
                    'Đề nghị chi phải gắn với đúng một chứng từ nguồn: đơn mua hàng hoặc yêu cầu đổi điểm.'
                )

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

    def action_revoke_misa_payment_request(self):
        for request in self:
            request._enqueue_revoke_job()
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

    def action_open_loyalty_reward_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yêu cầu đổi điểm',
            'res_model': 'hlv.loyalty.reward.request',
            'view_mode': 'form',
            'res_id': self.loyalty_reward_request_id.id,
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
            'purchase_order_id': self.purchase_order_id.id or False,
            'direction': 'payment_request',
        })
        self.write({'job_id': job.id, 'state': 'pending', 'error_msg': False})
        return job

    def _enqueue_revoke_job(self):
        self.ensure_one()
        if not self.org_refid:
            raise UserError('Đề nghị chi chưa được gửi MISA nên không có dữ liệu để thu hồi.')
        if self.state == 'deleted':
            raise UserError('Đề nghị chi này đã được thu hồi trên MISA.')
        existing = self.env['amis.sync.job'].sudo().search([
            ('payment_request_id', '=', self.id),
            ('direction', '=', 'payment_request_revoke'),
            ('status', 'in', ('pending', 'error')),
        ], limit=1)
        if existing:
            existing.write({'status': 'pending', 'retry_count': 0, 'error_msg': False})
            self.write({'job_id': existing.id, 'state': 'delete_pending', 'error_msg': False})
            return existing
        job = self.env['amis.sync.job'].sudo().create({
            'payment_request_id': self.id,
            'purchase_order_id': self.purchase_order_id.id or False,
            'direction': 'payment_request_revoke',
        })
        self.write({
            'job_id': job.id,
            'state': 'delete_pending',
            'error_msg': False,
            'state_updated_at': fields.Datetime.now(),
        })
        return job

    def _revoke_misa_payment_request(self):
        self.ensure_one()
        voucher_type = 3 if self.payment_method == 'bank' else 4
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        config.delete_payment_request(self.org_refid, voucher_type)
        self.sudo().write({
            'state': 'delete_pending',
            'error_msg': False,
            'state_updated_at': fields.Datetime.now(),
        })

    def _sync_payment_request_to_misa(self):
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        config.ensure_sync_ready()
        voucher_payload = self._prepare_misa_payment_request_payload(config)
        reference_items = self._prepare_misa_payment_request_references(voucher_payload)
        config.push_payment_request(voucher_payload, reference_items=reference_items)
        self.sudo().write({
            'org_refid': voucher_payload.get('org_refid') or '',
            'state': 'sent',
            'error_msg': False,
        })

    def _prepare_misa_payment_request_payload(self, config):
        self.ensure_one()
        if not self.partner_id:
            raise UserError('Đề nghị chi thiếu người nhận.')
        if not self.amount or self.amount <= 0:
            raise UserError('Số tiền đề nghị chi phải lớn hơn 0.')
        is_bank = self.payment_method == 'bank'
        if is_bank:
            if not self.company_bank_account_number:
                raise UserError('Chi tiền gửi bắt buộc phải có tài khoản chi của công ty.')
            if not self.vendor_bank_account_number or not self.vendor_bank_name:
                raise UserError('Chi tiền gửi bắt buộc phải có số tài khoản và ngân hàng nhận.')
            if not self.beneficiary_account_type:
                raise UserError('Vui lòng xác nhận tài khoản nhận là tài khoản công ty hay cá nhân.')
            if not (self.vendor_account_holder or '').strip():
                raise UserError('Chi tiền gửi bắt buộc phải có tên chủ tài khoản nhận.')

        branch_id = (config.misa_branch_id or '').strip()
        if not branch_id:
            raise UserError('Chưa cấu hình MISA Branch ID.')

        po = self.purchase_order_id
        dictionary_items = []
        account_object = self._ensure_misa_payment_account_object(
            config, self.partner_id, dictionary_items,
        )
        if dictionary_items:
            config.push_dictionary(dictionary_items)
            config.clear_dictionary_cache([1])

        org_refid = (self.org_refid or '').strip()
        if not org_refid:
            org_refid = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_payment_request|%d' % self.id))
            self.sudo().write({'org_refid': org_refid})

        refdate = self._misa_datetime(self.payment_date)
        amount = float(self.amount or 0.0)
        if self.loyalty_reward_request_id:
            default_memo = 'Chi đổi điểm Loyalty %s cho %s' % (
                self.loyalty_reward_request_id.name,
                self.partner_id.display_name,
            )
        else:
            default_memo = 'Đề nghị chi tiền nhà cung cấp %s theo đơn mua %s' % (
                self.partner_id.display_name,
                po.name,
            )
        memo = (self.memo or '').strip() or default_memo
        account_type_label = dict(self._fields['beneficiary_account_type'].selection).get(
            self.beneficiary_account_type, ''
        )
        if is_bank:
            memo = '[TK NHẬN: %s - CHỦ TK: %s] %s' % (
                account_type_label.upper(),
                (self.vendor_account_holder or '').strip(),
                memo,
            )
        currency = self.currency_id.name or 'VND'
        exchange_rate = float(getattr(po, 'currency_rate', 1.0) or 1.0) if po else 1.0
        account_object_id = account_object.get('account_object_id') or ''
        account_object_code = account_object.get('account_object_code') or ''
        account_object_name = account_object.get('account_object_name') or self.partner_id.display_name

        detail_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_payment_request_detail|%d' % self.id))
        voucher_type = 3 if is_bank else 4
        reftype = 1510 if is_bank else 1020
        credit_account = (self.credit_account or '1121') if is_bank else '1111'
        voucher = {
            'voucher_type': voucher_type,
            'org_refid': org_refid,
            'org_refno': self.name,
            'org_reftype': reftype,
            'org_reftype_name': 'Ủy nhiệm chi' if is_bank else 'Phiếu chi',
            'refid': org_refid,
            'refno': self.name,
            'reftype': reftype,
            'act_voucher_type': 0,
            'branch_id': branch_id,
            'reason_type_id': 43 if is_bank else 23,
            'refdate': refdate,
            'posted_date': refdate,
            'account_object_id': account_object_id,
            'account_object_code': account_object_code,
            'account_object_name': account_object_name,
            'account_object_address': self.partner_id.contact_address_complete or '',
            'account_object_contact_name': self.vendor_account_holder or account_object_name,
            'account_object_bank_account': self.vendor_bank_account_number or '',
            'account_object_bank_name': self.vendor_bank_name or '',
            'account_object_bank_branch_name': self.vendor_bank_branch or '',
            'bank_account_number': self.company_bank_account_number or '',
            'bank_name': self.company_bank_name or '',
            'currency_id': currency,
            'exchange_rate': exchange_rate,
            'journal_memo': memo,
            'custom_field5': account_type_label if is_bank else 'Tiền mặt',
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
                'credit_account': credit_account,
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
        if not is_bank:
            for field_name in (
                'account_object_bank_account', 'account_object_bank_name',
                'account_object_bank_branch_name', 'bank_account_number', 'bank_name',
            ):
                voucher.pop(field_name, None)
        return voucher

    def _ensure_misa_payment_account_object(self, config, partner, dictionary_items):
        """Reuse the purchase flow's account-object lookup/create contract."""
        self.ensure_one()
        purchase_helper = self.purchase_order_id or self.env['purchase.order']
        return purchase_helper._ensure_misa_account_object(config, partner, dictionary_items)

    def _prepare_misa_payment_request_references(self, voucher_payload):
        self.ensure_one()
        po = self.purchase_order_id
        if not po:
            return []
        po_org_refid = (po.misa_purchase_order_org_refid or '').strip()
        return [{
            'org_refid': voucher_payload.get('org_refid') or '',
            'org_refno': voucher_payload.get('org_refno') or self.name,
            'org_reftype': int(voucher_payload.get('org_reftype') or voucher_payload.get('reftype') or 0),
            'org_reftype_name': voucher_payload.get('org_reftype_name') or '',
            'org_refer_refid': po_org_refid or None,
            'org_refer_refno': po.name or '',
            'org_refer_reftype': 301,
            'org_refer_reftype_name': 'Đơn mua hàng',
            'sort_order': 1,
        }]

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


class HlvLoyaltyRewardRequestAmisPayment(models.Model):
    _inherit = 'hlv.loyalty.reward.request'

    def action_done(self):
        cash_requests = self.filtered(
            lambda request: request.state == 'pending' and request.request_type == 'cash'
        )
        result = super().action_done()
        for request in cash_requests:
            request._enqueue_loyalty_payment_request()
        return result

    def _enqueue_loyalty_payment_request(self):
        self.ensure_one()
        existing = self.env['amis.payment.request'].sudo().search([
            ('loyalty_reward_request_id', '=', self.id),
        ], limit=1)
        if existing:
            existing.action_enqueue_sync()
            return existing

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        bank_config = config.payment_bank_config_ids.filtered(
            lambda line: line.active
            and line.purpose == 'loyalty'
            and line.company_id == self.company_id
        )[:1]
        if not bank_config:
            bank_config = config.payment_bank_config_ids.filtered(
                lambda line: line.active
                and line.purpose == 'purchase'
                and line.company_id == self.company_id
            )[:1]
        company_bank = bank_config.company_bank_id if bank_config else self.company_id.partner_id.bank_ids[:1]
        partner = self.partner_id
        payment_request = self.env['amis.payment.request'].sudo().create({
            'loyalty_reward_request_id': self.id,
            'partner_id': partner.id,
            'company_id': self.company_id.id,
            'currency_id': self.company_id.currency_id.id,
            'amount': self.cash_value,
            'payment_date': fields.Date.context_today(self),
            'memo': 'Chi đổi điểm Loyalty %s - %s điểm cho %s' % (
                self.name,
                self.points_required,
                partner.display_name,
            ),
            'payment_method': 'bank',
            'company_bank_id': company_bank.id or False,
            'company_bank_account_number': company_bank.acc_number if company_bank else '',
            'company_bank_name': (
                company_bank.bank_id.name if company_bank and company_bank.bank_id else ''
            ),
            'vendor_bank_account_number': self.account_number or '',
            'vendor_bank_name': self.bank_name or '',
            'vendor_account_holder': self.account_name or partner.display_name,
            'beneficiary_account_type': 'company' if partner.is_company else 'personal',
            'debit_account': bank_config.debit_account if bank_config else '331',
            'credit_account': bank_config.credit_account if bank_config else '1121',
        })
        payment_request.action_enqueue_sync()
        _logger.info(
            'Loyalty reward request %s enqueued AMIS payment request %s (job %s).',
            self.name,
            payment_request.name,
            payment_request.job_id.id,
        )
        return payment_request
