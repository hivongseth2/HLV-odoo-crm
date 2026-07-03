# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MAX_RETRY = 3


class AmisCatalogSyncJob(models.Model):
    _name = 'amis.catalog.sync.job'
    _description = 'Hàng đợi đồng bộ danh mục MISA'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(string='Tên job', compute='_compute_name', store=True)
    config_id = fields.Many2one('amis.callback.config', string='Cấu hình', ondelete='set null')
    partner_id = fields.Many2one('res.partner', string='Nhà cung cấp', ondelete='set null', index=True)
    direction = fields.Selection([
        ('from_misa', 'MISA -> Odoo'),
        ('to_misa', 'Odoo -> MISA'),
    ], string='Hướng đồng bộ', required=True, default='from_misa', index=True)
    scope = fields.Selection([
        ('all', 'Tất cả danh mục'),
        ('unmapped', 'Danh mục mới/chưa map'),
        ('product', 'Sản phẩm'),
        ('vendor', 'Nhà cung cấp'),
    ], string='Phạm vi', required=True, default='all', index=True)
    trigger = fields.Selection([
        ('cron', 'Cron'),
        ('manual', 'Thủ công'),
        ('partner_save', 'Lưu nhà cung cấp'),
    ], string='Nguồn tạo', required=True, default='manual', index=True)
    status = fields.Selection([
        ('pending', 'Chờ xử lý'),
        ('running', 'Đang xử lý'),
        ('done', 'Thành công'),
        ('error', 'Lỗi'),
        ('skipped', 'Bỏ qua'),
    ], string='Trạng thái', default='pending', index=True)
    unmapped_only = fields.Boolean(string='Chỉ đồng bộ chưa map')
    create_missing = fields.Boolean(string='Tạo mới trên Odoo', default=True)
    product_skip = fields.Integer(string='Vị trí batch hàng hóa MISA', default=0)
    vendor_skip = fields.Integer(string='Vị trí batch nhà cung cấp MISA', default=0)
    batch_size = fields.Integer(string='Số item mỗi batch', default=100)
    unit_sync_done = fields.Boolean(string='Đã xử lý đơn vị tính')
    vendor_sync_done = fields.Boolean(string='Đã xử lý nhà cung cấp')
    retry_count = fields.Integer(string='Số lần thử', default=0)
    started_at = fields.Datetime(string='Bắt đầu lúc')
    processed_at = fields.Datetime(string='Xử lý lúc')
    error_msg = fields.Text(string='Lỗi cuối')
    summary = fields.Text(string='Tóm tắt')
    total_count = fields.Integer(string='Tổng item MISA')
    created_count = fields.Integer(string='Đã tạo')
    updated_count = fields.Integer(string='Đã cập nhật/map')
    skipped_count = fields.Integer(string='Bỏ qua')
    error_count = fields.Integer(string='Số lỗi')
    line_ids = fields.One2many('amis.catalog.sync.job.line', 'job_id', string='Chi tiết thay đổi')
    issue_line_ids = fields.One2many(
        'amis.catalog.sync.job.line',
        'job_id',
        string='Cần xử lý',
        domain=[('issue_type', '!=', False), ('resolved', '=', False)],
    )
    issue_count = fields.Integer(string='Cần xử lý', compute='_compute_issue_count')

    @api.depends('line_ids.issue_type', 'line_ids.resolved')
    def _compute_issue_count(self):
        grouped = self.env['amis.catalog.sync.job.line'].sudo().read_group(
            [('job_id', 'in', self.ids), ('issue_type', '!=', False), ('resolved', '=', False)],
            ['job_id'],
            ['job_id'],
        )
        counts = {item['job_id'][0]: item['job_id_count'] for item in grouped if item.get('job_id')}
        for job in self:
            job.issue_count = counts.get(job.id, 0)

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
    def enqueue_from_misa(self, config, trigger='manual', unmapped_only=False, create_missing=True, scope=None):
        scope = scope or ('unmapped' if unmapped_only else 'all')
        existing = self.sudo().search([
            ('direction', '=', 'from_misa'),
            ('scope', '=', scope),
            ('config_id', '=', config.id if config else False),
            ('unmapped_only', '=', bool(unmapped_only)),
            ('create_missing', '=', bool(create_missing)),
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
                raise ValueError('Chưa có cấu hình AMIS callback.')
            config.ensure_sync_ready()
            if self.direction == 'from_misa':
                if self.scope == 'product':
                    summary = config._sync_product_catalog_from_misa_to_odoo(
                        unmapped_only=self.unmapped_only,
                        job=self,
                    )
                elif self.scope == 'vendor':
                    summary = config._sync_vendor_catalog_from_misa_to_odoo(
                        unmapped_only=self.unmapped_only,
                        create_missing=self.create_missing,
                        job=self,
                    )
                else:
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
                    raise ValueError('Job đồng bộ NCC sang MISA thiếu partner_id.')
                operation = self.partner_id.with_context(skip_misa_partner_sync=True)._push_misa_vendor_dictionary(config, job=self)
                self.write({
                    'status': 'done',
                    'summary': 'Đã đồng bộ nhà cung cấp %s sang MISA.' % self.partner_id.display_name,
                    'total_count': 1,
                    'created_count': 1 if operation == 'create' else 0,
                    'updated_count': 1 if operation != 'create' else 0,
                    'skipped_count': 0,
                    'error_count': 0,
                    'processed_at': fields.Datetime.now(),
                    'error_msg': False,
                })
            else:
                raise ValueError('Hướng đồng bộ danh mục không hỗ trợ: %s' % self.direction)
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
                'vendor_skip': 0,
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

    def add_change_line(
        self, data_type, operation, odoo_model, res_id, misa_id, code, name, change_summary,
        issue_type=False,
    ):
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
            'issue_type': issue_type or False,
        })


class AmisCatalogSyncJobLine(models.Model):
    _name = 'amis.catalog.sync.job.line'
    _description = 'Chi tiết đồng bộ danh mục MISA'
    _order = 'id asc'

    job_id = fields.Many2one('amis.catalog.sync.job', string='Job', required=True, ondelete='cascade', index=True)
    data_type = fields.Selection([
        ('unit', 'Đơn vị tính'),
        ('product', 'Hàng hóa'),
        ('vendor', 'Nhà cung cấp'),
    ], string='Loại danh mục', required=True, index=True)
    operation = fields.Selection([
        ('create', 'Tạo mới'),
        ('update', 'Cập nhật'),
        ('map', 'Map ID'),
        ('skip', 'Bỏ qua'),
        ('error', 'Lỗi'),
    ], string='Thao tác', required=True, index=True)
    odoo_model = fields.Char(string='Model Odoo')
    res_id = fields.Integer(string='ID Odoo')
    misa_id = fields.Char(string='ID MISA', index=True)
    code = fields.Char(string='Mã')
    name = fields.Char(string='Tên')
    change_summary = fields.Text(string='Thay đổi')
    issue_type = fields.Selection([
        ('uom_mismatch', 'ĐVT lệch thật'),
    ], string='Loại cần xử lý', index=True)
    resolved = fields.Boolean(string='Đã xử lý', default=False, index=True)
    resolved_note = fields.Text(string='Ghi chú xử lý')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('issue_type') and self._is_uom_issue_vals(vals):
                vals['issue_type'] = 'uom_mismatch'
        return super().create(vals_list)

    @api.model
    def _is_uom_issue_vals(self, vals):
        if vals.get('data_type') != 'product' or vals.get('operation') != 'skip':
            return False
        summary = (vals.get('change_summary') or '').casefold()
        return 'đvt' in summary and (
            'lệch thật' in summary
            or 'cần xử lý' in summary
            or 'bỏ qua cập nhật' in summary
        )

    def init(self):
        self.env.cr.execute("""
            UPDATE amis_catalog_sync_job_line
               SET issue_type = 'uom_mismatch'
             WHERE issue_type IS NULL
               AND data_type = 'product'
               AND operation = 'skip'
               AND (
                    change_summary ILIKE '%%ĐVT%%'
                    OR change_summary ILIKE '%%UoM needs manual check%%'
               )
               AND (
                    change_summary ILIKE '%%lệch thật%%'
                    OR change_summary ILIKE '%%cần xử lý%%'
                    OR change_summary ILIKE '%%bỏ qua cập nhật%%'
                    OR change_summary ILIKE '%%manual check%%'
               )
        """)

    def action_open_odoo_record(self):
        self.ensure_one()
        if not self.odoo_model or not self.res_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': self.name or self.code or self.odoo_model,
            'res_model': self.odoo_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_mark_resolved(self):
        self.write({'resolved': True})
        return True

    def action_mark_unresolved(self):
        self.write({'resolved': False})
        return True
