# -*- coding: utf-8 -*-
import logging

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
            check.total_difference = sum(check.line_ids.mapped('difference'))
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
                    'scanned_qty': 0,
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
                'difference': line.difference,
                'reason': reason,
                'notes': notes or '',
            })
            line.discrepancy_id = disc.id
        return {'success': True}

    @api.model
    def get_daily_stats(self):
        """Thống kê kiểm kê theo ngày cho user hiện tại"""
        today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0)
        my_checks_today = self.search([
            ('user_id', '=', self.env.user.id),
            ('create_date', '>=', today_start),
        ])
        all_checks_today = self.search([
            ('create_date', '>=', today_start),
        ])

        def _stats(checks):
            confirmed = checks.filtered(lambda c: c.state == 'confirmed')
            pending = checks.filtered(lambda c: c.state == 'pending_approval')
            in_progress = checks.filtered(lambda c: c.state in ['draft', 'in_progress'])
            return {
                'total': len(checks),
                'confirmed': len(confirmed),
                'pending_approval': len(pending),
                'in_progress': len(in_progress),
                'total_products': sum(checks.mapped('product_count')),
                'total_scans': sum(checks.mapped('scan_count')),
                'total_difference': sum(checks.mapped('total_difference')),
            }

        return {
            'success': True,
            'my_stats': _stats(my_checks_today),
            'team_stats': _stats(all_checks_today),
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
            'is_manager': is_manager,
        }

    @api.model
    def save_scanner_settings(self, approval_required, auto_confirm):
        """Lưu cấu hình scanner (chỉ manager)"""
        if not self.env.user.has_group('stock.group_stock_manager'):
            return {'success': False, 'error': _('Chỉ quản lý kho mới được thay đổi cài đặt')}
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('hlv_inventory.approval_required', 'True' if approval_required else 'False')
        ICP.set_param('hlv_inventory.auto_confirm', 'True' if auto_confirm else 'False')
        return {'success': True}

    @api.model
    def get_pending_approvals(self):
        """Lấy danh sách phiên chờ duyệt (cho manager)"""
        if not self.env.user.has_group('stock.group_stock_manager'):
            return []
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
            'confirmed_time': c.confirmed_time.strftime('%d/%m %H:%M') if c.confirmed_time else '',
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
