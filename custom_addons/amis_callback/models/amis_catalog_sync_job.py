# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MAX_RETRY = 3


class AmisCatalogSyncJob(models.Model):
    _name = 'amis.catalog.sync.job'
    _description = 'Hang doi dong bo danh muc MISA'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(string='Ten job', compute='_compute_name', store=True)
    config_id = fields.Many2one('amis.callback.config', string='Cau hinh', ondelete='set null')
    partner_id = fields.Many2one('res.partner', string='Nha cung cap', ondelete='set null', index=True)
    direction = fields.Selection([
        ('from_misa', 'MISA -> Odoo'),
        ('to_misa', 'Odoo -> MISA'),
    ], string='Huong dong bo', required=True, default='from_misa', index=True)
    scope = fields.Selection([
        ('all', 'Tat ca danh muc'),
        ('unmapped', 'Danh muc moi/chua map'),
        ('vendor', 'Nha cung cap'),
    ], string='Pham vi', required=True, default='all', index=True)
    trigger = fields.Selection([
        ('cron', 'Cron'),
        ('manual', 'Thu cong'),
        ('partner_save', 'Luu nha cung cap'),
    ], string='Nguon tao', required=True, default='manual', index=True)
    status = fields.Selection([
        ('pending', 'Cho xu ly'),
        ('running', 'Dang xu ly'),
        ('done', 'Thanh cong'),
        ('error', 'Loi'),
        ('skipped', 'Bo qua'),
    ], string='Trang thai', default='pending', index=True)
    unmapped_only = fields.Boolean(string='Chi dong bo chua map')
    create_missing = fields.Boolean(string='Tao moi tren Odoo', default=True)
    product_skip = fields.Integer(string='Vi tri batch hang hoa MISA', default=0)
    batch_size = fields.Integer(string='So item moi batch', default=100)
    unit_sync_done = fields.Boolean(string='Da xu ly don vi tinh')
    vendor_sync_done = fields.Boolean(string='Da xu ly nha cung cap')
    retry_count = fields.Integer(string='So lan thu', default=0)
    started_at = fields.Datetime(string='Bat dau luc')
    processed_at = fields.Datetime(string='Xu ly luc')
    error_msg = fields.Text(string='Loi cuoi')
    summary = fields.Text(string='Tom tat')
    total_count = fields.Integer(string='Tong item MISA')
    created_count = fields.Integer(string='Da tao')
    updated_count = fields.Integer(string='Da cap nhat/map')
    skipped_count = fields.Integer(string='Bo qua')
    error_count = fields.Integer(string='So loi')
    line_ids = fields.One2many('amis.catalog.sync.job.line', 'job_id', string='Chi tiet thay doi')

    @api.depends('direction', 'scope', 'create_date')
    def _compute_name(self):
        for job in self:
            created = fields.Datetime.to_string(job.create_date) if job.create_date else ''
            job.name = '%s - %s - %s' % (
                dict(job._fields['direction'].selection).get(job.direction, job.direction),
                dict(job._fields['scope'].selection).get(job.scope, job.scope),
                created,
            )

    @api.model
    def enqueue_from_misa(self, config, trigger='manual', unmapped_only=False, create_missing=True):
        scope = 'unmapped' if unmapped_only else 'all'
        existing = self.sudo().search([
            ('direction', '=', 'from_misa'),
            ('scope', '=', scope),
            ('status', 'in', ('pending', 'running')),
        ], limit=1)
        if existing:
            return existing
        return self.sudo().create({
            'config_id': config.id if config else False,
            'direction': 'from_misa',
            'scope': scope,
            'trigger': trigger,
            'unmapped_only': bool(unmapped_only),
            'create_missing': bool(create_missing),
        })

    @api.model
    def enqueue_vendor_to_misa(self, config, partner, trigger='partner_save'):
        if not partner:
            return self
        existing = self.sudo().search([
            ('direction', '=', 'to_misa'),
            ('scope', '=', 'vendor'),
            ('partner_id', '=', partner.id),
            ('status', 'in', ('pending', 'running')),
        ], limit=1)
        if existing:
            return existing
        return self.sudo().create({
            'config_id': config.id if config else False,
            'partner_id': partner.id,
            'direction': 'to_misa',
            'scope': 'vendor',
            'trigger': trigger,
            'unmapped_only': False,
            'create_missing': True,
        })

    @api.model
    def _process_pending(self):
        job_ids = self.search([
            ('status', '=', 'pending'),
            ('retry_count', '<', MAX_RETRY),
        ], order='create_date asc').ids
        _logger.info('AMIS catalog sync queue: xu ly %d jobs', len(job_ids))
        for job_id in job_ids:
            try:
                import odoo
                with odoo.registry(self.env.cr.dbname).cursor() as cr:
                    env = odoo.api.Environment(cr, self.env.uid, {})
                    job = env['amis.catalog.sync.job'].browse(job_id)
                    if job.status != 'pending':
                        continue
                    job._execute()
                    cr.commit()
            except Exception:
                _logger.exception('AMIS catalog sync job %d: unhandled error in cursor', job_id)

    def _execute(self):
        self.ensure_one()
        self.write({
            'status': 'running',
            'started_at': fields.Datetime.now(),
            'error_msg': False,
        })
        try:
            config = self.config_id or self.env['amis.callback.config'].sudo().search([], limit=1)
            if not config:
                raise ValueError('Chua co cau hinh AMIS callback.')
            config.ensure_sync_ready()
            if self.direction == 'from_misa':
                summary = config._sync_catalog_from_misa_to_odoo(
                    unmapped_only=self.unmapped_only,
                    create_missing=self.create_missing,
                    job=self,
                )
                totals = summary.get('totals') or {}
                complete = bool(summary.get('complete', True))
                self.write({
                    'status': 'done' if complete else 'pending',
                    'summary': summary.get('message') or '',
                    'total_count': self.total_count + int(totals.get('total') or 0),
                    'created_count': self.created_count + int(totals.get('created') or 0),
                    'updated_count': self.updated_count + int(totals.get('updated') or 0),
                    'skipped_count': self.skipped_count + int(totals.get('skipped') or 0),
                    'error_count': self.error_count + int(totals.get('error') or 0),
                    'processed_at': fields.Datetime.now(),
                    'error_msg': False,
                })
            elif self.direction == 'to_misa' and self.scope == 'vendor':
                if not self.partner_id:
                    raise ValueError('Job dong bo NCC sang MISA thieu partner_id.')
                operation = self.partner_id.with_context(skip_misa_partner_sync=True)._push_misa_vendor_dictionary(config, job=self)
                self.write({
                    'status': 'done',
                    'summary': 'Da dong bo nha cung cap %s sang MISA.' % self.partner_id.display_name,
                    'total_count': 1,
                    'created_count': 1 if operation == 'create' else 0,
                    'updated_count': 1 if operation != 'create' else 0,
                    'skipped_count': 0,
                    'error_count': 0,
                    'processed_at': fields.Datetime.now(),
                    'error_msg': False,
                })
            else:
                raise ValueError('Huong dong bo danh muc khong ho tro: %s' % self.direction)
        except Exception as exc:
            self.write({
                'retry_count': self.retry_count + 1,
                'status': 'error' if self.retry_count + 1 >= MAX_RETRY else 'pending',
                'error_msg': str(exc)[:2000],
                'processed_at': fields.Datetime.now(),
            })
            _logger.exception('AMIS catalog sync job %d failed (retry %d/%d)', self.id, self.retry_count, MAX_RETRY)

    def action_retry(self):
        for job in self:
            job.write({
                'status': 'pending',
                'retry_count': 0,
                'error_msg': False,
                'processed_at': False,
                'product_skip': 0,
                'unit_sync_done': False,
                'vendor_sync_done': False,
                'total_count': 0,
                'created_count': 0,
                'updated_count': 0,
                'skipped_count': 0,
                'error_count': 0,
            })
        return True

    def action_run_now(self):
        import odoo
        for job in self:
            if job.status not in ('pending', 'error'):
                continue
            try:
                with odoo.registry(self.env.cr.dbname).cursor() as cr:
                    env = odoo.api.Environment(cr, self.env.uid, {})
                    j = env['amis.catalog.sync.job'].browse(job.id)
                    j.write({'status': 'pending', 'retry_count': 0, 'error_msg': False})
                    j._execute()
                    cr.commit()
            except Exception:
                _logger.exception('AMIS catalog sync job %d: action_run_now failed', job.id)
        return True

    def add_change_line(self, data_type, operation, odoo_model, res_id, misa_id, code, name, change_summary):
        self.ensure_one()
        self.env['amis.catalog.sync.job.line'].sudo().create({
            'job_id': self.id,
            'data_type': data_type,
            'operation': operation,
            'odoo_model': odoo_model or '',
            'res_id': res_id or 0,
            'misa_id': misa_id or '',
            'code': code or '',
            'name': name or '',
            'change_summary': change_summary or '',
        })


class AmisCatalogSyncJobLine(models.Model):
    _name = 'amis.catalog.sync.job.line'
    _description = 'Chi tiet dong bo danh muc MISA'
    _order = 'id asc'

    job_id = fields.Many2one('amis.catalog.sync.job', string='Job', required=True, ondelete='cascade', index=True)
    data_type = fields.Selection([
        ('unit', 'Don vi tinh'),
        ('product', 'Hang hoa'),
        ('vendor', 'Nha cung cap'),
    ], string='Loai danh muc', required=True, index=True)
    operation = fields.Selection([
        ('create', 'Tao moi'),
        ('update', 'Cap nhat'),
        ('map', 'Map ID'),
        ('skip', 'Bo qua'),
        ('error', 'Loi'),
    ], string='Thao tac', required=True, index=True)
    odoo_model = fields.Char(string='Model Odoo')
    res_id = fields.Integer(string='ID Odoo')
    misa_id = fields.Char(string='ID MISA', index=True)
    code = fields.Char(string='Ma')
    name = fields.Char(string='Ten')
    change_summary = fields.Text(string='Thay doi')
