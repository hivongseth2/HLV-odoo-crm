# -*- coding: utf-8 -*-
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

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

    def action_open_uom_resolution_wizard(self):
        self.ensure_one()
        self._check_uom_resolution_line()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Xử lý ĐVT lệch thật'),
            'res_model': 'amis.catalog.uom.issue.resolve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_issue_line_id': self.id,
            },
        }

    def _check_uom_resolution_line(self):
        self.ensure_one()
        if self.issue_type != 'uom_mismatch':
            raise UserError(_('Chỉ xử lý tự động cho dòng ĐVT lệch thật.'))
        if self.resolved:
            raise UserError(_('Dòng này đã được đánh dấu xử lý.'))
        if self.odoo_model != 'product.product' or not self.res_id:
            raise UserError(_('Dòng ĐVT lệch thật chưa trỏ tới sản phẩm Odoo hợp lệ.'))


class AmisCatalogUomIssueResolveWizard(models.TransientModel):
    _name = 'amis.catalog.uom.issue.resolve.wizard'
    _description = 'Xử lý ĐVT lệch thật danh mục MISA'

    issue_line_id = fields.Many2one(
        'amis.catalog.sync.job.line',
        string='Dòng cần xử lý',
        required=True,
        readonly=True,
    )
    old_product_id = fields.Many2one(
        'product.product',
        string='Sản phẩm cũ',
        compute='_compute_preview',
        readonly=True,
    )
    target_uom_id = fields.Many2one(
        'uom.uom',
        string='ĐVT theo MISA',
        compute='_compute_preview',
        readonly=True,
    )
    current_uom_id = fields.Many2one(
        'uom.uom',
        string='ĐVT hiện tại',
        compute='_compute_preview',
        readonly=True,
    )
    current_qty = fields.Float(string='Tồn kho hiện tại', compute='_compute_preview', readonly=True)
    transfer_code = fields.Char(string='Mã tham chiếu chuyển sang SP mới', compute='_compute_preview', readonly=True)
    transfer_barcode = fields.Char(string='Barcode chuyển sang SP mới', compute='_compute_preview', readonly=True)
    warning_text = fields.Text(string='Cảnh báo', compute='_compute_preview', readonly=True)
    confirm = fields.Boolean(string='Tôi xác nhận tạo sản phẩm mới và lưu trữ sản phẩm cũ')
    note = fields.Text(string='Ghi chú xử lý')

    @api.depends('issue_line_id')
    def _compute_preview(self):
        for wizard in self:
            if not wizard.issue_line_id:
                wizard.old_product_id = False
                wizard.target_uom_id = False
                wizard.current_uom_id = False
                wizard.current_qty = 0.0
                wizard.transfer_code = ''
                wizard.transfer_barcode = ''
                wizard.warning_text = ''
                continue
            product = wizard.issue_line_id._uom_resolution_product()
            target_uom = wizard.issue_line_id._uom_resolution_target_uom()
            wizard.old_product_id = product
            wizard.target_uom_id = target_uom
            wizard.current_uom_id = product.uom_id
            wizard.current_qty = product.qty_available if product else 0.0
            wizard.transfer_code = product.default_code or ''
            wizard.transfer_barcode = product.barcode or ''
            wizard.warning_text = _(
                'Hệ thống sẽ tạo sản phẩm mới dùng ĐVT MISA, chuyển mã tham chiếu/barcode/MISA ID '
                'và tồn kho hiện tại sang sản phẩm mới, rồi lưu trữ sản phẩm cũ. '
                'Nếu sản phẩm cũ còn đơn bán, đơn mua hoặc phiếu kho/chuyển kho chưa xử lý thì thao tác sẽ bị chặn.'
            )

    def action_confirm(self):
        self.ensure_one()
        if not self.confirm:
            raise UserError(_('Bạn phải xác nhận trước khi xử lý ĐVT lệch thật.'))
        return self.issue_line_id._resolve_uom_mismatch_by_duplicate(note=self.note or '')


def _line_uom_resolution_product(self):
    self.ensure_one()
    self._check_uom_resolution_line()
    product = self.env['product.product'].sudo().with_context(active_test=False).browse(self.res_id)
    if not product.exists():
        raise UserError(_('Không tìm thấy sản phẩm Odoo cần xử lý.'))
    return product


def _line_uom_resolution_config(self):
    self.ensure_one()
    config = self.job_id.config_id or self.env['amis.callback.config'].sudo().search([], limit=1)
    if not config:
        raise UserError(_('Chưa có cấu hình AMIS callback để đọc ĐVT MISA.'))
    return config


def _line_uom_resolution_target_uom_from_summary(self):
    self.ensure_one()
    summary = self.change_summary or ''
    match = re.search(r'MISA=([^.;\n]+)', summary)
    if not match:
        return self.env['uom.uom']

    Uom = self.env['uom.uom'].sudo().with_context(active_test=False)
    for raw_part in match.group(1).split(','):
        name = re.sub(r'\[[^\]]*\]', '', raw_part).strip()
        if not name or re.fullmatch(r'[0-9a-fA-F-]{32,}', name):
            continue
        candidates = Uom.search([('name', '=ilike', name)])
        if not candidates:
            continue
        target = candidates.filtered(
            lambda uom: (uom.category_id.name or '').strip().casefold() != 'stopused'
        )[:1] or candidates[:1]
        if target:
            return target
    return self.env['uom.uom']


def _line_uom_resolution_misa_item(self):
    self.ensure_one()
    config = self._uom_resolution_config()
    misa_id = (self.misa_id or '').strip().lower()
    code = (self.code or '').strip()
    if misa_id:
        item = config.find_dictionary_item_by_code(2, 'inventory_item_id', misa_id, max_pages=1000)
        if item:
            return item
    if code:
        item = config.find_dictionary_item_by_code(2, 'inventory_item_code', code, max_pages=1000)
        if item:
            return item
    for item in config._get_all_dictionary(2):
        item_id = (item.get('inventory_item_id') or '').strip().lower()
        item_code = (item.get('inventory_item_code') or '').strip()
        if (misa_id and item_id == misa_id) or (code and item_code == code):
            return item
    raise UserError(_('Không tìm thấy hàng hóa MISA tương ứng để lấy ĐVT.'))


def _line_uom_resolution_target_uom(self):
    self.ensure_one()
    summary_uom = self._uom_resolution_target_uom_from_summary()
    if summary_uom:
        return summary_uom
    config = self._uom_resolution_config()
    item = self._uom_resolution_misa_item()
    Uom = self.env['uom.uom'].sudo().with_context(active_test=False)
    entries = config._misa_catalog_product_unit_entries(item)
    if not entries:
        raise UserError(_('Hàng hóa MISA chưa có thông tin ĐVT để xử lý.'))
    entry = entries[0]
    unit_id = (entry.get('unit_id') or '').strip()
    unit_name = (entry.get('unit_name') or '').strip()
    target_uom = Uom
    if unit_id:
        target_uom = Uom.search([('misa_unit_id', '=', unit_id)], limit=1)
    if not target_uom and unit_name:
        target_uom = Uom.search([('name', '=ilike', unit_name)], limit=1)
        if target_uom and unit_id and not (target_uom.misa_unit_id or '').strip():
            target_uom.write({'misa_unit_id': unit_id})
    if not target_uom:
        raise UserError(_('Không tìm thấy ĐVT Odoo tương ứng với ĐVT MISA: %s') % (unit_name or unit_id))
    return target_uom


def _line_uom_resolution_blockers(self, product):
    self.ensure_one()
    blockers = []
    checks = [
        ('sale.order.line', [('product_id', '=', product.id), ('state', 'not in', ('cancel', 'done'))], _('Đơn bán chưa xử lý')),
        ('purchase.order.line', [('product_id', '=', product.id), ('state', 'not in', ('cancel', 'done'))], _('Đơn mua chưa xử lý')),
        ('stock.move', [('product_id', '=', product.id), ('state', 'not in', ('cancel', 'done'))], _('Phiếu kho/chuyển kho chưa xử lý')),
        ('stock.move.line', [('product_id', '=', product.id), ('state', 'not in', ('cancel', 'done'))], _('Dòng phiếu kho chưa xử lý')),
    ]
    for model_name, domain, label in checks:
        try:
            Model = self.env[model_name].sudo()
        except KeyError:
            continue
        if 'state' not in Model._fields:
            continue
        records = Model.search(domain, limit=6)
        if records:
            sample = ', '.join(records[:5].mapped('display_name'))
            more = '...' if len(records) > 5 else ''
            blockers.append('%s: %s%s' % (label, sample, more))

    Quant = self.env['stock.quant'].sudo()
    reserved_quants = Quant.search([
        ('product_id', '=', product.id),
        ('reserved_quantity', '>', 0),
    ], limit=6)
    if reserved_quants:
        sample = ', '.join(reserved_quants[:5].mapped('location_id.display_name'))
        more = '...' if len(reserved_quants) > 5 else ''
        blockers.append(_('Tồn kho đang được giữ chỗ tại: %s%s') % (sample, more))

    return blockers


def _line_uom_resolution_copy_lot(self, old_lot, new_product):
    if not old_lot:
        return old_lot
    Lot = self.env['stock.lot'].sudo()
    domain = [
        ('name', '=', old_lot.name),
        ('product_id', '=', new_product.id),
    ]
    if 'company_id' in Lot._fields:
        domain.append(('company_id', '=', old_lot.company_id.id if old_lot.company_id else False))
    new_lot = Lot.search(domain, limit=1)
    if new_lot:
        return new_lot
    vals = {
        'name': old_lot.name,
        'product_id': new_product.id,
    }
    if 'company_id' in Lot._fields:
        vals['company_id'] = old_lot.company_id.id if old_lot.company_id else False
    return Lot.create(vals)


def _line_uom_resolution_transfer_quants(self, old_product, new_product):
    Quant = self.env['stock.quant'].sudo()
    quants = Quant.search([
        ('product_id', '=', old_product.id),
        ('quantity', '!=', 0),
        ('location_id.usage', 'in', ('internal', 'transit')),
    ])
    moved_qty = 0.0
    for quant in quants:
        qty = quant.quantity
        if float_compare(qty, 0.0, precision_rounding=old_product.uom_id.rounding) == 0:
            continue
        new_lot = self._uom_resolution_copy_lot(quant.lot_id, new_product)
        Quant._update_available_quantity(
            old_product,
            quant.location_id,
            -qty,
            lot_id=quant.lot_id,
            package_id=quant.package_id,
            owner_id=quant.owner_id,
        )
        Quant._update_available_quantity(
            new_product,
            quant.location_id,
            qty,
            lot_id=new_lot,
            package_id=quant.package_id,
            owner_id=quant.owner_id,
        )
        moved_qty += qty
    return moved_qty


def _line_uom_resolution_post_log(self, new_product, old_product, old_code, old_barcode, old_uom, new_uom, moved_qty, note):
    old_link = '<a href="#" data-oe-model="product.product" data-oe-id="%s">%s</a>' % (
        old_product.id,
        old_product.display_name,
    )
    body = _(
        'Đã xử lý ĐVT lệch MISA bằng cách tạo sản phẩm mới này từ sản phẩm cũ %(old_link)s.<br/>'
        'ĐVT cũ: %(old_uom)s; ĐVT mới theo MISA: %(new_uom)s.<br/>'
        'Đã chuyển mã tham chiếu: %(code)s; barcode: %(barcode)s; tồn kho chuyển: %(qty)s.<br/>'
        'Ghi chú: %(note)s'
    ) % {
        'old_link': old_link,
        'old_uom': old_uom.display_name if old_uom else '',
        'new_uom': new_uom.display_name if new_uom else '',
        'code': old_code or '',
        'barcode': old_barcode or '',
        'qty': moved_qty,
        'note': note or '',
    }
    target = new_product if hasattr(new_product, 'message_post') else new_product.product_tmpl_id
    target.message_post(body=body, subtype_xmlid='mail.mt_note')

    new_link = '<a href="#" data-oe-model="product.product" data-oe-id="%s">%s</a>' % (
        new_product.id,
        new_product.display_name,
    )
    old_body = _('Sản phẩm đã được lưu trữ sau khi tạo sản phẩm mới xử lý ĐVT MISA: %s') % new_link
    old_target = old_product if hasattr(old_product, 'message_post') else old_product.product_tmpl_id
    old_target.message_post(body=old_body, subtype_xmlid='mail.mt_note')


def _line_resolve_uom_mismatch_by_duplicate(self, note=''):
    self.ensure_one()
    product = self._uom_resolution_product()
    target_uom = self._uom_resolution_target_uom()
    if len(product.product_tmpl_id.product_variant_ids) > 1:
        raise UserError(_('Chưa hỗ trợ xử lý tự động cho sản phẩm có nhiều biến thể.'))
    blockers = self._uom_resolution_blockers(product)
    if blockers:
        raise UserError(_('Không thể xử lý ĐVT vì sản phẩm cũ còn chứng từ cần xử lý:\n%s') % '\n'.join(blockers))

    old_code = product.default_code or ''
    old_barcode = product.barcode or ''
    old_misa_id = (getattr(product, 'misa_inventory_item_id', '') or '').strip()
    old_uom = product.uom_id
    new_misa_id = (self.misa_id or old_misa_id or '').strip()

    old_clear_vals = {}
    if 'default_code' in product._fields:
        old_clear_vals['default_code'] = False
    if 'barcode' in product._fields:
        old_clear_vals['barcode'] = False
    if 'misa_inventory_item_id' in product._fields:
        old_clear_vals['misa_inventory_item_id'] = False
    if old_clear_vals:
        product.write(old_clear_vals)

    copy_vals = {
        'uom_id': target_uom.id,
        'uom_po_id': target_uom.id,
        'active': True,
    }
    if old_code and 'default_code' in product._fields:
        copy_vals['default_code'] = old_code
    if old_barcode and 'barcode' in product._fields:
        copy_vals['barcode'] = old_barcode
    if new_misa_id and 'misa_inventory_item_id' in product._fields:
        copy_vals['misa_inventory_item_id'] = new_misa_id

    new_product = product.copy(copy_vals)
    moved_qty = self._uom_resolution_transfer_quants(product, new_product)
    if 'active' in product._fields:
        product.write({'active': False})
    elif 'active' in product.product_tmpl_id._fields:
        product.product_tmpl_id.write({'active': False})

    self.write({
        'resolved': True,
        'resolved_note': _('Đã tạo sản phẩm mới %(new)s từ sản phẩm cũ %(old)s. %(note)s') % {
            'new': new_product.display_name,
            'old': product.display_name,
            'note': note or '',
        },
    })
    self._uom_resolution_post_log(
        new_product, product, old_code, old_barcode, old_uom, target_uom, moved_qty, note
    )
    return {
        'type': 'ir.actions.act_window',
        'name': _('Sản phẩm mới sau xử lý ĐVT'),
        'res_model': 'product.product',
        'res_id': new_product.id,
        'view_mode': 'form',
        'target': 'current',
    }


AmisCatalogSyncJobLine._uom_resolution_product = _line_uom_resolution_product
AmisCatalogSyncJobLine._uom_resolution_config = _line_uom_resolution_config
AmisCatalogSyncJobLine._uom_resolution_target_uom_from_summary = _line_uom_resolution_target_uom_from_summary
AmisCatalogSyncJobLine._uom_resolution_misa_item = _line_uom_resolution_misa_item
AmisCatalogSyncJobLine._uom_resolution_target_uom = _line_uom_resolution_target_uom
AmisCatalogSyncJobLine._uom_resolution_blockers = _line_uom_resolution_blockers
AmisCatalogSyncJobLine._uom_resolution_copy_lot = _line_uom_resolution_copy_lot
AmisCatalogSyncJobLine._uom_resolution_transfer_quants = _line_uom_resolution_transfer_quants
AmisCatalogSyncJobLine._uom_resolution_post_log = _line_uom_resolution_post_log
AmisCatalogSyncJobLine._resolve_uom_mismatch_by_duplicate = _line_resolve_uom_mismatch_by_duplicate
