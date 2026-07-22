# -*- coding: utf-8 -*-
import logging
import pytz
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command

_logger = logging.getLogger(__name__)


class InventoryCheck(models.Model):
    """
    Model chính cho phiên kiểm kê tồn kho
    """
    _name = 'inventory.check'
    _description = 'Phiên Kiểm Kê Tồn Kho'
    _order = 'create_date desc'
    
    # ========== Basic Info ==========
    name = fields.Char(
        string='Mã Phiên Kiểm Kê',
        required=True,
        copy=False,
        readonly=True,
        default='New'
    )
    
    user_id = fields.Many2one(
        'res.users',
        string='Người Kiểm Kê',
        default=lambda self: self.env.user,
        required=True,
        readonly=True
    )
    
    location_id = fields.Many2one(
        'stock.location',
        string='Vị Trí Kho',
        domain=[('usage', '=', 'internal')],
        help='Vị trí kho cần kiểm kê'
    )
    
    device_id = fields.Char(
        string='Device ID',
        help='Browser fingerprint hoặc device identifier'
    )
    
    # ========== Time Info ==========
    start_time = fields.Datetime(
        string='Bắt Đầu',
        default=fields.Datetime.now,
        readonly=True
    )
    
    last_scan_time = fields.Datetime(
        string='Quét Lần Cuối'
    )
    
    confirmed_time = fields.Datetime(
        string='Xác Nhận Lúc'
    )
    
    # ========== Status ==========
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('in_progress', 'Đang Kiểm Kê'),
            ('pending_approval', 'Chờ Duyệt'),
            ('confirmed', 'Đã Xác Nhận'),
            ('locked', 'Bị Khóa'),
            ('cancelled', 'Đã Hủy'),
        ],
        string='Trạng Thái',
        default='draft',
        tracking=True
    )
    
    # ========== Lines & Details ==========
    line_ids = fields.One2many(
        'inventory.check.line',
        'check_id',
        string='Chi Tiết Kiểm Kê',
        copy=True
    )
    
    discrepancy_ids = fields.One2many(
        'inventory.discrepancy',
        'check_id',
        string='Chênh Lệch',
        copy=False
    )
    
    # ========== Statistics ==========
    product_count = fields.Integer(
        string='Số Sản Phẩm Quét',
        compute='_compute_stats',
        store=True
    )
    
    scan_count = fields.Integer(
        string='Tổng Lượt Quét',
        compute='_compute_stats',
        store=True
    )
    
    total_theoretical_qty = fields.Float(
        string='Tồn Kho Lý Thuyết',
        compute='_compute_stats',
        store=True
    )
    
    total_scanned_qty = fields.Float(
        string='Tồn Kho Thực Tế',
        compute='_compute_stats',
        store=True
    )
    
    total_difference = fields.Float(
        string='Tổng Chênh Lệch',
        compute='_compute_stats',
        store=True
    )
    
    discrepancy_count = fields.Integer(
        string='Số Chênh Lệch',
        compute='_compute_stats',
        store=True
    )
    
    # ========== Locking ==========
    locked_move_ids = fields.Many2many(
        'stock.move',
        'inventory_check_stock_move_rel',
        'check_id',
        'move_id',
        string='Stock Move Bị Khóa',
        copy=False
    )
    
    has_pending_outbound = fields.Boolean(
        string='Có Outbound Chờ',
        compute='_compute_pending_moves',
        store=False
    )
    
    pending_move_ids = fields.One2many(
        'stock.move',
        compute='_get_pending_moves',
        string='Stock Move Chờ Xử Lý'
    )
    
    notes = fields.Text(
        string='Ghi Chú'
    )
    
    # ========== Audit Trail ==========
    created_by = fields.Many2one(
        'res.users',
        string='Tạo Bởi',
        default=lambda self: self.env.user,
        readonly=True
    )
    
    confirmed_by = fields.Many2one(
        'res.users',
        string='Xác Nhận Bởi',
        readonly=True
    )

    approved_by = fields.Many2one(
        'res.users',
        string='Duyệt Bởi',
        readonly=True
    )

    approved_time = fields.Datetime(
        string='Duyệt Lúc',
        readonly=True
    )
    
    @api.depends('line_ids', 'line_ids.scanned_qty', 'line_ids.theoretical_qty', 'discrepancy_ids')
    def _compute_stats(self):
        """Tính toán các thống kê cơ bản"""
        for check in self:
            check.product_count = len(check.line_ids)
            check.scan_count = int(sum(check.line_ids.mapped('scanned_qty')))
            check.total_theoretical_qty = sum(check.line_ids.mapped('theoretical_qty'))
            check.total_scanned_qty = sum(check.line_ids.mapped('scanned_qty'))
            # Dùng tổng giá trị tuyệt đối để +1 và -1 không triệt tiêu nhau
            check.total_difference = sum(abs(d) for d in check.line_ids.mapped('difference'))
            check.discrepancy_count = len(check.discrepancy_ids)

    @api.depends('location_id')
    def _compute_pending_moves(self):
        """Kiểm tra có outbound pending cho location"""
        for check in self:
            if not check.location_id:
                check.has_pending_outbound = False
                continue
            
            pending_moves = self.env['stock.move'].search([
                ('location_id', '=', check.location_id.id),
                ('state', 'in', ['confirmed', 'waiting', 'partially_available']),
                ('picking_type_id.code', 'in', ['outgoing', 'internal']),
            ])
            check.has_pending_outbound = len(pending_moves) > 0

    def _get_pending_moves(self):
        """Lấy danh sách stock move đang chờ"""
        for check in self:
            if check.location_id:
                check.pending_move_ids = self.env['stock.move'].search([
                    ('location_id', '=', check.location_id.id),
                    ('state', 'in', ['confirmed', 'waiting', 'partially_available']),
                    ('picking_type_id.code', 'in', ['outgoing', 'internal']),
                ])
            else:
                check.pending_move_ids = self.env['stock.move'].browse()

    # ========== Sequence ==========
    @api.model_create_multi
    def create(self, vals_list):
        """Auto generate sequence"""
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('inventory.check') or 'CHECK'
        return super().create(vals_list)

    # ========== Actions ==========
    def action_start_check(self):
        """Bắt đầu kiểm kê - lock stock moves"""
        for check in self:
            if check.state != 'draft':
                raise ValidationError(_('Chỉ có thể bắt đầu kiểm kê từ trạng thái Nháp'))
            
            # Lock outbound moves của location này
            check._lock_location_moves()
            
            check.state = 'in_progress'
            check.start_time = fields.Datetime.now()

    def action_confirm_check(self):
        """Xác nhận kiểm kê — nếu approval_required thì chuyển pending_approval"""
        for check in self:
            if check.state != 'in_progress':
                raise ValidationError(_('Chỉ có thể xác nhận kiểm kê đang tiến hành'))

            lines_without_reason = check.line_ids.filtered(
                lambda l: l.difference != 0 and not l.discrepancy_id
            )
            if lines_without_reason:
                raise UserError(_(
                    'Cần ghi nhận lý do chênh lệch cho %d sản phẩm trước khi xác nhận'
                    % len(lines_without_reason)
                ))

            approval_required = self.env['ir.config_parameter'].sudo().get_param(
                'hlv_inventory.approval_required', 'False'
            ) == 'True'

            if approval_required:
                check.state = 'pending_approval'
                check.confirmed_time = fields.Datetime.now()
                check.confirmed_by = self.env.user
            else:
                check._apply_and_confirm()

    def _apply_and_confirm(self):
        """Áp dụng adjustment + unlock + confirmed"""
        self.ensure_one()
        self._create_inventory_adjustment()
        self._unlock_location_moves()
        self.state = 'confirmed'
        self.confirmed_time = fields.Datetime.now()
        self.confirmed_by = self.env.user
        # Update discrepancy states to confirmed
        self.discrepancy_ids.filtered(lambda d: d.state == 'draft').write({'state': 'confirmed'})

    def action_approve(self):
        """Quản lý duyệt phiên kiểm kê pending_approval"""
        for check in self:
            if check.state != 'pending_approval':
                raise ValidationError(_('Chỉ có thể duyệt phiên đang chờ duyệt'))
            check._apply_and_confirm()
            check.approved_by = self.env.user
            check.approved_time = fields.Datetime.now()

    def action_reject(self):
        """Từ chối phiên kiểm kê — trở về in_progress"""
        for check in self:
            if check.state != 'pending_approval':
                raise ValidationError(_('Chỉ có thể từ chối phiên đang chờ duyệt'))
            check.state = 'in_progress'

    def action_cancel(self):
        """Hủy kiểm kê"""
        for check in self:
            # Unlock moves nếu có
            check._unlock_location_moves()
            
            check.state = 'cancelled'

    def action_lock_moves_manually(self):
        """Lock stock moves của location (có thể gọi bất kỳ lúc nào)"""
        for check in self:
            check._lock_location_moves()
            self.env.user.notify_warning(
                message=_('Đã khóa tất cả outbound moves của %s') % check.location_id.name
            )

    def action_unlock_moves_manually(self):
        """Unlock stock moves của location"""
        for check in self:
            check._unlock_location_moves()
            self.env.user.notify_warning(
                message=_('Đã mở khóa tất cả outbound moves của %s') % check.location_id.name
            )

    # ========== Helper Methods ==========
    def _lock_location_moves(self):
        """Lock outbound moves của location"""
        self.ensure_one()
        
        # Tìm tất cả outbound/internal moves của location này
        moves_to_lock = self.env['stock.move'].search([
            ('location_id', '=', self.location_id.id),
            ('state', 'in', ['confirmed', 'waiting', 'partially_available']),
            ('picking_type_id.code', 'in', ['outgoing', 'internal']),
        ])
        
        for move in moves_to_lock:
            try:
                move.write({'is_locked': True})
                self.locked_move_ids = [Command.link(move.id)]
            except Exception as e:
                _logger.warning(f'Không thể lock move {move.name}: {str(e)}')

    def _unlock_location_moves(self):
        """Unlock outbound moves của location"""
        self.ensure_one()
        
        for move in self.locked_move_ids:
            try:
                move.write({'is_locked': False})
            except Exception as e:
                _logger.warning(f'Không thể unlock move {move.name}: {str(e)}')
        
        self.locked_move_ids = [Command.clear()]

    def _create_inventory_adjustment(self):
        """Áp dụng Inventory Adjustment qua stock.quant (Odoo 17/18)"""
        self.ensure_one()

        quants_to_apply = self.env['stock.quant']

        for line in self.line_ids:
            domain = [
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', line.location_id.id),
                ('lot_id', '=', line.lot_id.id if line.lot_id else False),
                ('package_id', '=', line.package_id.id if line.package_id else False),
            ]
            quant = self.env['stock.quant'].search(domain, limit=1)

            if quant:
                quant.inventory_quantity = line.scanned_qty
                quant.inventory_quantity_set = True
            else:
                # Sản phẩm không tồn tại ở kho, tạo quant mới với inventory_quantity
                quant = self.env['stock.quant'].create({
                    'product_id': line.product_id.id,
                    'location_id': line.location_id.id,
                    'lot_id': line.lot_id.id if line.lot_id else False,
                    'package_id': line.package_id.id if line.package_id else False,
                    'inventory_quantity': line.scanned_qty,
                    'inventory_quantity_set': True,
                })

            quants_to_apply |= quant

        # Áp dụng toàn bộ điều chỉnh, tạo stock.move điều chỉnh tồn kho
        if quants_to_apply:
            quants_to_apply.action_apply_inventory()

    # ========== API Methods for OWL Component ==========
    @api.model
    def get_or_create_active_check(self, device_id, location_id=None):
        """Khôi phục phiên kiểm kê cũ hoặc tạo mới"""
        domain = [
            ('user_id', '=', self.env.user.id),
            ('state', 'in', ['draft', 'in_progress']),
            ('device_id', '=', device_id)
        ]
        
        if location_id:
            domain.append(('location_id', '=', location_id))
        
        check = self.search(domain, limit=1, order='start_time desc')
        
        if not check:
            vals = {
                'user_id': self.env.user.id,
                'device_id': device_id,
                'state': 'draft',
            }
            if location_id:
                vals['location_id'] = location_id
            
            check = self.create(vals)
        
        return check._get_check_data()

    def _get_check_data(self):
        """Trả về dữ liệu kiểm kê cho frontend"""
        self.ensure_one()
        return {
            'success': True,
            'check_id': self.id,
            'name': self.name,
            'location_id': self.location_id.id if self.location_id else False,
            'location_name': self.location_id.display_name if self.location_id else '',
            'state': self.state,
            'product_count': self.product_count,
            'scan_count': self.scan_count,
            'total_theoretical_qty': self.total_theoretical_qty,
            'total_scanned_qty': self.total_scanned_qty,
            'total_difference': self.total_difference,
            'has_pending_outbound': self.has_pending_outbound,
            'lines': self._get_lines_data(),
            'discrepancies': self._get_discrepancies_data(),
        }

    def _get_lines_data(self):
        """Trả về dữ liệu lines"""
        return [{
            'id': line.id,
            'product_id': line.product_id.id,
            'product_name': line.product_id.name,
            'product_code': line.product_id.default_code,
            'barcode': line.product_id.barcode,
            'uom_name': line.product_id.uom_id.name,
            'scanned_qty': line.scanned_qty,
            'theoretical_qty': line.theoretical_qty,
            'difference': line.difference,
            'location_id': line.location_id.id,
            'lot_id': line.lot_id.id,
            'package_id': line.package_id.id,
            'discrepancy_id': line.discrepancy_id.id if line.discrepancy_id else False,
        } for line in self.line_ids]

    def _get_discrepancies_data(self):
        """Trả về dữ liệu chênh lệch"""
        return [{
            'id': disc.id,
            'line_id': disc.line_id.id,
            'product_name': disc.line_id.product_id.name,
            'difference': disc.line_id.difference,
            'reason': disc.reason,
            'notes': disc.notes,
        } for disc in self.discrepancy_ids]

    @api.model
    def get_active_sessions(self):
        """Lấy danh sách phiên kiểm kê đang hoạt động của user (tất cả thiết bị)"""
        checks = self.search([
            ('user_id', '=', self.env.user.id),
            ('state', 'in', ['draft', 'in_progress']),
        ], order='write_date desc', limit=10)
        return [{
            'check_id': c.id,
            'name': c.name,
            'location_id': c.location_id.id if c.location_id else False,
            'location_name': c.location_id.display_name if c.location_id else 'Chưa chọn vị trí',
            'state': c.state,
            'product_count': c.product_count,
            'scan_count': c.scan_count,
            'write_date': c.write_date.strftime('%d/%m %H:%M') if c.write_date else '',
        } for c in checks]

    @api.model
    def resume_check(self, check_id):
        """Tiếp tục một phiên kiểm kê cụ thể theo ID"""
        check = self.browse(check_id)
        if not check.exists() or check.user_id != self.env.user:
            return {'success': False, 'error': _('Không tìm thấy phiên kiểm kê')}
        if check.state not in ['draft', 'in_progress']:
            return {'success': False, 'error': _('Phiên kiểm kê đã hoàn thành hoặc bị hủy')}
        return check._get_check_data()

    @api.model
    def register_scan(self, check_id, product_id, location_id, qty=1, lot_id=False, package_id=False):
        """Xử lý mỗi lần quét barcode"""
        check = self.browse(check_id)
        
        if not check.exists() or check.state not in ['draft', 'in_progress']:
            return {'success': False, 'error': _('Phiên kiểm kê không hợp lệ')}
        
        # Nếu chưa bắt đầu, tự động bắt đầu
        if check.state == 'draft':
            check.action_start_check()
        
        # Kiểm tra có outbound pending
        if check.has_pending_outbound:
            return {
                'success': False,
                'error': _('Cảnh báo: Có outbound chờ xử lý. Vui lòng hoàn thành kiểm kê và thoát!'),
                'warning': True,
            }
        
        # Tìm hoặc tạo line
        domain = [
            ('check_id', '=', check_id),
            ('product_id', '=', product_id),
            ('location_id', '=', location_id),
        ]
        
        if lot_id:
            domain.append(('lot_id', '=', lot_id))
        else:
            domain.append(('lot_id', '=', False))
        
        if package_id:
            domain.append(('package_id', '=', package_id))
        else:
            domain.append(('package_id', '=', False))
        
        line = self.env['inventory.check.line'].search(domain, limit=1)
        
        if line:
            line.scanned_qty += qty
        else:
            # Lấy tồn kho lý thuyết
            quant_domain = [
                ('product_id', '=', product_id),
                ('location_id', '=', location_id),
            ]
            if lot_id:
                quant_domain.append(('lot_id', '=', lot_id))
            if package_id:
                quant_domain.append(('package_id', '=', package_id))
            
            quants = self.env['stock.quant'].search(quant_domain)
            theoretical_qty = sum(quants.mapped('quantity'))
            
            line = self.env['inventory.check.line'].create({
                'check_id': check_id,
                'product_id': product_id,
                'location_id': location_id,
                'lot_id': lot_id,
                'package_id': package_id,
                'scanned_qty': qty,
                'theoretical_qty': theoretical_qty,
            })
        
        check.write({'last_scan_time': fields.Datetime.now()})
        
        return {
            'success': True,
            'line_id': line.id,
            'product_id': line.product_id.id,
            'product_name': line.product_id.name,
            'scanned_qty': line.scanned_qty,
            'theoretical_qty': line.theoretical_qty,
            'difference': line.difference,
            'product_count': check.product_count,
            'total_scans': check.scan_count,
        }

    @api.model
    def update_line_qty(self, check_id, line_id, new_qty):
        """Cập nhật số lượng line"""
        line = self.env['inventory.check.line'].browse(line_id)
        if line.check_id.id != check_id:
            return {'success': False, 'error': 'Lỗi bảo mật'}
        
        line.write({'scanned_qty': new_qty})
        
        return {
            'success': True,
            'scanned_qty': line.scanned_qty,
            'difference': line.difference,
        }

    @api.model
    def remove_line(self, check_id, line_id):
        """Xóa một line khỏi kiểm kê"""
        line = self.env['inventory.check.line'].browse(line_id)
        if line.check_id.id != check_id:
            return {'success': False, 'error': 'Lỗi bảo mật'}
        
        check = line.check_id
        line.unlink()
        
        return {'success': True}

    @api.model
    def set_location(self, check_id, location_id):
        """Đặt vị trí kiểm kê và tải danh sách sản phẩm từ stock.quant"""
        check = self.browse(check_id)
        if not check.exists():
            return {'success': False, 'error': 'Không tìm thấy phiên kiểm kê'}

        check.write({'location_id': location_id})

        # Pre-populate lines với tồn kho lý thuyết tại vị trí
        quants = self.env['stock.quant'].search([
            ('location_id', '=', location_id),
            ('quantity', '>', 0),
        ])

        # Check continue_counting setting
        ICP = self.env['ir.config_parameter'].sudo()
        continue_counting = ICP.get_param('hlv_inventory.continue_counting', 'False') == 'True'

        for quant in quants:
            existing = self.env['inventory.check.line'].search([
                ('check_id', '=', check_id),
                ('product_id', '=', quant.product_id.id),
                ('location_id', '=', location_id),
                ('lot_id', '=', quant.lot_id.id if quant.lot_id else False),
                ('package_id', '=', quant.package_id.id if quant.package_id else False),
            ], limit=1)
            if not existing:
                self.env['inventory.check.line'].create({
                    'check_id': check_id,
                    'product_id': quant.product_id.id,
                    'location_id': location_id,
                    'lot_id': quant.lot_id.id if quant.lot_id else False,
                    'package_id': quant.package_id.id if quant.package_id else False,
                    'scanned_qty': quant.quantity if continue_counting else 0,
                    'theoretical_qty': quant.quantity,
                })

        # Auto-start check when location is confirmed
        if check.state == 'draft':
            check.state = 'in_progress'
            check.start_time = fields.Datetime.now()

        return check._get_check_data()

    @api.model
    def save_discrepancy(self, line_id, reason, notes):
        """Lưu lý do chênh lệch từ inline dialog"""
        line = self.env['inventory.check.line'].browse(line_id)
        if not line.exists() or line.check_id.user_id != self.env.user:
            return {'success': False, 'error': _('Không tìm thấy dòng kiểm kê')}
        if not reason:
            return {'success': False, 'error': _('Vui lòng chọn lý do chênh lệch')}

        if line.discrepancy_id:
            line.discrepancy_id.write({'reason': reason, 'notes': notes or ''})
        else:
            disc = self.env['inventory.discrepancy'].create({
                'check_id': line.check_id.id,
                'line_id': line.id,
                'reason': reason,
                'notes': notes or '',
            })
            line.discrepancy_id = disc.id
        return {'success': True}

    @api.model
    def create_new_check(self, device_id):
        """Tạo phên kiểm kê mới (không resume phên cũ)"""
        check = self.create({
            'user_id': self.env.user.id,
            'device_id': device_id,
            'state': 'draft',
        })
        return check._get_check_data()

    @api.model
    def get_check_data(self, check_id):
        """Lấy dữ liệu phên theo id, không tạo mới"""
        check = self.browse(check_id)
        if not check.exists():
            return {'success': False, 'error': 'Không tìm thấy phiên'}
        if check.user_id.id != self.env.user.id:
            return {'success': False, 'error': 'Không có quyền truy cập phiên này'}
        return check._get_check_data()

    @api.model
    def get_daily_stats(self, date_str=None):
        """Thống kê kiểm kê theo ngày — chi tiết"""
        tz = pytz.timezone(self.env.user.tz or 'Asia/Ho_Chi_Minh')

        def _fmt_time(dt):
            if not dt:
                return ''
            return pytz.utc.localize(dt).astimezone(tz).strftime('%H:%M')

        if date_str:
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
            today_start_local = tz.localize(datetime(d.year, d.month, d.day, 0, 0, 0))
        else:
            now_local = pytz.utc.localize(datetime.utcnow()).astimezone(tz)
            today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

        today_start_utc = today_start_local.astimezone(pytz.utc).replace(tzinfo=None)
        today_end_utc = (today_start_local + timedelta(days=1)).astimezone(pytz.utc).replace(tzinfo=None)

        is_manager = self.env.user.has_group('stock.group_stock_manager')

        my_checks_today = self.search([
            ('user_id', '=', self.env.user.id),
            ('create_date', '>=', today_start_utc),
            ('create_date', '<', today_end_utc),
        ])
        all_checks_today = self.search([
            ('create_date', '>=', today_start_utc),
            ('create_date', '<', today_end_utc),
        ])

        def _stats(checks):
            confirmed = checks.filtered(lambda c: c.state == 'confirmed')
            pending = checks.filtered(lambda c: c.state == 'pending_approval')
            in_progress = checks.filtered(lambda c: c.state in ['draft', 'in_progress'])
            locations = set(checks.filtered(lambda c: c.location_id).mapped('location_id.id'))
            return {
                'total': len(checks),
                'confirmed': len(confirmed),
                'pending_approval': len(pending),
                'in_progress': len(in_progress),
                'total_products': sum(checks.mapped('product_count')),
                'total_scans': sum(checks.mapped('scan_count')),
                'total_difference': sum(abs(c.total_difference) for c in checks),
                'locations_checked': len(locations),
            }

        # My checks list
        my_checks_list = [{
            'id': c.id,
            'name': c.name,
            'location_name': c.location_id.display_name if c.location_id else 'Chưa chọn',
            'state': c.state,
            'product_count': c.product_count,
            'scan_count': c.scan_count,
            'total_difference': sum(abs(d) for d in c.line_ids.mapped('difference')),
            'start_time': _fmt_time(c.start_time),
            'confirmed_time': _fmt_time(c.confirmed_time),
        } for c in my_checks_today.sorted('start_time', reverse=True)]

        # Per-user breakdown (manager only)
        team_by_user = []
        if is_manager:
            users = all_checks_today.mapped('user_id')
            for user in users:
                user_checks = all_checks_today.filtered(lambda c, u=user: c.user_id == u)
                team_by_user.append({
                    'user_name': user.name,
                    'total': len(user_checks),
                    'confirmed': len(user_checks.filtered(lambda c: c.state == 'confirmed')),
                    'in_progress': len(user_checks.filtered(lambda c: c.state in ['draft', 'in_progress'])),
                    'total_products': sum(user_checks.mapped('product_count')),
                    'total_scans': sum(user_checks.mapped('scan_count')),
                    'total_difference': sum(abs(c.total_difference) for c in user_checks),
                })
            team_by_user.sort(key=lambda x: x['total'], reverse=True)

        return {
            'success': True,
            'my_stats': _stats(my_checks_today),
            'team_stats': _stats(all_checks_today) if is_manager else None,
            'my_checks': my_checks_list,
            'team_by_user': team_by_user,
            'is_manager': is_manager,
        }

    @api.model
    def get_check_detail(self, check_id):
        """Lấy chi tiết dòng sản phẩm của 1 phiên kiểm kê"""
        check = self.browse(check_id)
        if not check.exists():
            return {'success': False, 'error': 'Phiên không tồn tại'}
        # Only allow owner or manager to view
        is_manager = self.env.user.has_group('stock.group_stock_manager')
        if check.user_id.id != self.env.user.id and not is_manager:
            return {'success': False, 'error': 'Không có quyền xem phiên này'}

        tz = pytz.timezone(self.env.user.tz or 'Asia/Ho_Chi_Minh')

        def _fmt(dt):
            if not dt:
                return ''
            return pytz.utc.localize(dt).astimezone(tz).strftime('%H:%M')

        state_labels = {
            'draft': 'Nháp', 'in_progress': 'Đang làm',
            'pending_approval': 'Chờ duyệt', 'confirmed': 'Hoàn thành',
            'locked': 'Bị khóa', 'cancelled': 'Đã hủy',
        }

        lines = [{
            'id': l.id,
            'product_name': l.product_id.display_name if l.product_id else '',
            'product_barcode': l.product_id.barcode or '',
            'lot_name': l.lot_id.name if l.lot_id else '',
            'scanned_qty': l.scanned_qty,
            'theoretical_qty': l.theoretical_qty,
            'difference': l.difference,
            'uom': l.product_id.uom_id.name if l.product_id and l.product_id.uom_id else '',
        } for l in check.line_ids.sorted('create_date')]

        return {
            'success': True,
            'id': check.id,
            'name': check.name,
            'location_name': check.location_id.display_name if check.location_id else '',
            'user_name': check.user_id.name,
            'state': check.state,
            'state_label': state_labels.get(check.state, check.state),
            'start_time': _fmt(check.start_time),
            'confirmed_time': _fmt(check.confirmed_time),
            'product_count': check.product_count,
            'total_difference': check.total_difference,
            'lines': lines,
        }

    @api.model
    def get_scanner_settings(self):
        """Trả về cấu hình scanner cho frontend"""
        ICP = self.env['ir.config_parameter'].sudo()
        is_manager = self.env.user.has_group('stock.group_stock_manager')
        return {
            'success': True,
            'approval_required': ICP.get_param('hlv_inventory.approval_required', 'False') == 'True',
            'auto_confirm': ICP.get_param('hlv_inventory.auto_confirm', 'False') == 'True',
            'skip_discrepancy_reason': ICP.get_param('hlv_inventory.skip_discrepancy_reason', 'False') == 'True',
            'continue_counting': ICP.get_param('hlv_inventory.continue_counting', 'False') == 'True',
            'is_manager': is_manager,
        }

    @api.model
    def save_scanner_settings(self, approval_required, auto_confirm, skip_discrepancy_reason=False, continue_counting=False):
        """Lưu cấu hình scanner (chỉ manager)"""
        if not self.env.user.has_group('stock.group_stock_manager'):
            return {'success': False, 'error': _('Chỉ quản lý kho mới được thay đổi cài đặt')}
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('hlv_inventory.approval_required', 'True' if approval_required else 'False')
        ICP.set_param('hlv_inventory.auto_confirm', 'True' if auto_confirm else 'False')
        ICP.set_param('hlv_inventory.skip_discrepancy_reason', 'True' if skip_discrepancy_reason else 'False')
        ICP.set_param('hlv_inventory.continue_counting', 'True' if continue_counting else 'False')
        return {'success': True}

    @api.model
    def get_pending_approvals(self):
        """Lấy danh sách phiên chờ duyệt (cho manager)"""
        if not self.env.user.has_group('stock.group_stock_manager'):
            return []
        tz = pytz.timezone(self.env.user.tz or 'Asia/Ho_Chi_Minh')

        def _fmt(dt):
            if not dt:
                return ''
            return pytz.utc.localize(dt).astimezone(tz).strftime('%d/%m %H:%M')

        checks = self.search([
            ('state', '=', 'pending_approval'),
        ], order='confirmed_time desc', limit=50)
        return [{
            'check_id': c.id,
            'name': c.name,
            'user_name': c.user_id.name,
            'location_name': c.location_id.display_name if c.location_id else '',
            'product_count': c.product_count,
            'total_difference': c.total_difference,
            'confirmed_time': _fmt(c.confirmed_time),
        } for c in checks]

    @api.model
    def approve_check(self, check_id):
        """Duyệt phiên kiểm kê từ frontend (manager only)"""
        if not self.env.user.has_group('stock.group_stock_manager'):
            return {'success': False, 'error': _('Chỉ quản lý kho mới được duyệt')}
        check = self.browse(check_id)
        if not check.exists() or check.state != 'pending_approval':
            return {'success': False, 'error': _('Phiên không hợp lệ hoặc không ở trạng thái chờ duyệt')}
        check.action_approve()
        return {'success': True}

    @api.model
    def reject_check(self, check_id):
        """Từ chối phiên kiểm kê từ frontend (manager only)"""
        if not self.env.user.has_group('stock.group_stock_manager'):
            return {'success': False, 'error': _('Chỉ quản lý kho mới được từ chối')}
        check = self.browse(check_id)
        if not check.exists() or check.state != 'pending_approval':
            return {'success': False, 'error': _('Phiên không hợp lệ')}
        check.action_reject()
        return {'success': True}

    @api.model
    def search_location(self, barcode):
        """Tìm location theo barcode hoặc tên"""
        # Ưu tiên barcode chính xác
        location = self.env['stock.location'].search([
            ('barcode', '=', barcode), 
            ('usage', '=', 'internal')
        ], limit=1)
        
        if not location:
            # Tìm theo tên nếu ko có barcode
            location = self.env['stock.location'].search([
                ('name', 'ilike', barcode), 
                ('usage', '=', 'internal')
            ], limit=1)

        if location:
            return {
                'success': True, 
                'location_id': location.id, 
                'location_name': location.display_name
            }
        return {'success': False, 'error': f'Không tìm thấy vị trí: {barcode}'}

    @api.model
    def get_location_stock(self, barcode):
        """Trả về tồn kho tại vị trí ứng với barcode (chỉ xem, không sửa)"""
        location = self.env['stock.location'].search([
            ('barcode', '=', barcode),
            ('usage', '=', 'internal')
        ], limit=1)
        if not location:
            location = self.env['stock.location'].search([
                ('complete_name', 'ilike', barcode),
                ('usage', '=', 'internal')
            ], limit=1)
        if not location:
            return {'success': False, 'error': f'Không tìm thấy vị trí: {barcode}'}

        quants = self.env['stock.quant'].search([
            ('location_id', '=', location.id),
            ('product_id.active', '=', True),
        ])
        items = []
        for q in quants.sorted(key=lambda r: r.product_id.display_name):
            if q.quantity == 0:
                continue
            items.append({
                'product_id': q.product_id.id,
                'product_name': q.product_id.display_name,
                'product_code': q.product_id.default_code or '',
                'lot_name': q.lot_id.name if q.lot_id else '',
                'quantity': q.quantity,
                'uom_name': q.product_id.uom_id.name,
            })
        total_quantity = sum(i['quantity'] for i in items)
        return {
            'success': True,
            'location_id': location.id,
            'location_name': location.display_name,
            'items': items,
            'total_quantity': total_quantity,
        }

    @api.model
    def search_product(self, barcode):
        """Tìm product theo barcode, default_code, hoặc name"""
        product = self.env['product.product'].search([('barcode', '=', barcode)], limit=1)
        
        if not product:
            product = self.env['product.product'].search([
                '|', 
                ('default_code', 'ilike', barcode),
                ('name', 'ilike', barcode)
            ], limit=1)

        if not product:
            return {'success': False, 'error': f"Không tìm thấy sản phẩm: {barcode}"}
            
        return {
            'success': True,
            'product_id': product.id,
            'product_code': product.default_code or '',
            'product_name': product.name,
            'barcode': product.barcode or '',
            'uom_id': product.uom_id.id,
            'uom_name': product.uom_id.name,
        }
