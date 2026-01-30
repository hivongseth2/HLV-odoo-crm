# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import datetime, timedelta


class InventoryScanSession(models.Model):
    _name = 'inventory.scan.session'
    _description = 'Inventory Scan Session - Phiên quét kiểm kê'
    _order = 'start_time desc'

    name = fields.Char(
        string='Session ID',
        required=True,
        index=True,
        help='UUID từ frontend hoặc tự động tạo'
    )
    device_id = fields.Char(
        string='Device Fingerprint',
        required=True,
        index=True,
        help='Để phân biệt các thiết bị dùng chung account'
    )
    user_id = fields.Many2one(
        'res.users',
        string='User',
        default=lambda self: self.env.user,
        required=True,
        index=True
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        help='Vị trí được quét',
        index=True
    )
    
    state = fields.Selection([
        ('active', 'Đang quét'),
        ('confirmed', 'Đã xác nhận'),
        ('cancelled', 'Đã hủy')
    ], default='active', required=True, string='Trạng thái', index=True)
    
    line_ids = fields.One2many(
        'inventory.scan.line',
        'session_id',
        string='Scan Lines'
    )
    scan_count = fields.Integer(
        string='Số lần quét',
        compute='_compute_scan_count',
        store=True
    )
    product_count = fields.Integer(
        string='Số sản phẩm',
        compute='_compute_product_count',
        store=True
    )
    
    start_time = fields.Datetime(
        string='Bắt đầu',
        default=fields.Datetime.now,
        required=True
    )
    last_scan_time = fields.Datetime(string='Quét cuối')
    confirmed_time = fields.Datetime(string='Xác nhận lúc')
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )

    @api.depends('line_ids', 'line_ids.scanned_qty')
    def _compute_scan_count(self):
        for session in self:
            session.scan_count = sum(session.line_ids.mapped('scanned_qty'))

    @api.depends('line_ids')
    def _compute_product_count(self):
        for session in self:
            session.product_count = len(session.line_ids)

    # =========================================================================
    # API Methods cho Frontend
    # =========================================================================

    @api.model
    def get_or_create_active_session(self, device_id, location_id=None):
        """
        Tìm hoặc tạo session active cho user/device hiện tại.
        ĐÂY LÀ CƠ CHẾ KHÔI PHỤC DỮ LIỆU KHI RELOAD TRANG.
        
        Returns: dict với session info và tất cả lines đã quét
        """
        if not device_id:
            return {'success': False, 'error': 'Missing device_id'}

        # Tìm session active của user + device
        domain = [
            ('user_id', '=', self.env.user.id),
            ('device_id', '=', device_id),
            ('state', '=', 'active'),
        ]
        if location_id:
            domain.append(('location_id', '=', location_id))

        session = self.sudo().search(domain, limit=1, order='start_time desc')

        if session:
            # Trả về session hiện có với tất cả lines
            return session._get_session_data()
        
        # Tạo session mới
        session = self.sudo().create({
            'name': f"SCAN-{self.env.user.id}-{device_id[:8]}-{fields.Datetime.now().strftime('%H%M%S')}",
            'device_id': device_id,
            'location_id': location_id,
            'user_id': self.env.user.id,
        })
        
        return session._get_session_data()

    def _get_session_data(self):
        """Trả về dữ liệu session cho frontend"""
        self.ensure_one()
        lines_data = []
        
        for line in self.line_ids:
            lines_data.append({
                'id': line.id,
                'product_id': line.product_id.id,
                'product_code': line.product_id.default_code or '',
                'product_name': line.product_id.display_name,
                'product_barcode': line.product_id.barcode or '',
                'uom_name': line.product_id.uom_id.name or 'Cái',
                'scanned_qty': line.scanned_qty,
                'theoretical_qty': line.theoretical_qty,
                'difference': line.difference,
                'location_id': line.location_id.id if line.location_id else self.location_id.id,
                'location_name': (line.location_id or self.location_id).display_name if (line.location_id or self.location_id) else '',
                'lot_id': line.lot_id.id if line.lot_id else False,
                'lot_name': line.lot_id.name if line.lot_id else '',
                'package_id': line.package_id.id if line.package_id else False,
                'package_name': line.package_id.name if line.package_id else '',
            })
        
        return {
            'success': True,
            'session_id': self.id,
            'session_name': self.name,
            'device_id': self.device_id,
            'state': self.state,
            'location_id': self.location_id.id if self.location_id else False,
            'location_name': self.location_id.display_name if self.location_id else '',
            'product_count': self.product_count,
            'scan_count': self.scan_count,
            'lines': lines_data,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'last_scan_time': self.last_scan_time.isoformat() if self.last_scan_time else None,
        }

    @api.model
    def register_scan(self, session_id, product_id, location_id, qty=1, lot_id=False, package_id=False):
        """
        Ghi nhận 1 lần quét từ frontend.
        Nếu sản phẩm đã có trong session → tăng số lượng
        Nếu chưa có → tạo line mới
        
        Returns: dict với thông tin line được cập nhật
        """
        session = self.sudo().browse(session_id)
        if not session.exists() or session.state != 'active':
            return {'success': False, 'error': 'Session không hợp lệ hoặc đã đóng'}

        if not product_id or not location_id:
            return {'success': False, 'error': 'Thiếu product_id hoặc location_id'}

        # Cập nhật location của session nếu chưa có
        if not session.location_id:
            session.write({'location_id': location_id})

        ScanLine = self.env['inventory.scan.line'].sudo()
        
        # Tìm line hiện có cho sản phẩm này
        existing_line = ScanLine.search([
            ('session_id', '=', session_id),
            ('product_id', '=', product_id),
            ('location_id', '=', location_id),
            ('lot_id', '=', lot_id if lot_id else False),
        ], limit=1)

        if existing_line:
            # Tăng số lượng
            new_qty = existing_line.scanned_qty + qty
            existing_line.write({'scanned_qty': new_qty})
            line = existing_line
        else:
            # Lấy số lượng lý thuyết từ stock.quant
            theoretical_qty = self._get_theoretical_qty(product_id, location_id, lot_id)
            
            # Tạo line mới
            line = ScanLine.create({
                'session_id': session_id,
                'product_id': product_id,
                'location_id': location_id,
                'scanned_qty': qty,
                'theoretical_qty': theoretical_qty,
                'lot_id': lot_id if lot_id else False,
                'package_id': package_id if package_id else False,
            })

        # Cập nhật last_scan_time
        session.write({'last_scan_time': fields.Datetime.now()})

        product = self.env['product.product'].sudo().browse(product_id)
        
        return {
            'success': True,
            'line_id': line.id,
            'product_id': product_id,
            'product_code': product.default_code or '',
            'product_name': product.display_name,
            'uom_name': product.uom_id.name or 'Cái',
            'scanned_qty': line.scanned_qty,
            'theoretical_qty': line.theoretical_qty,
            'difference': line.difference,
            'product_count': session.product_count,
            'total_scans': session.scan_count,
        }

    @api.model
    def _get_theoretical_qty(self, product_id, location_id, lot_id=False):
        """Lấy số lượng tồn kho lý thuyết từ stock.quant"""
        domain = [
            ('product_id', '=', product_id),
            ('location_id', '=', location_id),
        ]
        if lot_id:
            domain.append(('lot_id', '=', lot_id))
        else:
            domain.append(('lot_id', '=', False))
            
        quant = self.env['stock.quant'].sudo().search(domain, limit=1)
        return quant.quantity if quant else 0.0

    def update_line_qty(self, line_id, new_qty):
        """Cập nhật số lượng của 1 line (dùng cho +1, +10, set qty)"""
        self.ensure_one()
        if self.state != 'active':
            return {'success': False, 'error': 'Session đã đóng'}
            
        line = self.env['inventory.scan.line'].sudo().browse(line_id)
        if not line.exists() or line.session_id.id != self.id:
            return {'success': False, 'error': 'Line không hợp lệ'}
        
        line.write({'scanned_qty': max(0, new_qty)})
        self.write({'last_scan_time': fields.Datetime.now()})
        
        return {
            'success': True,
            'line_id': line.id,
            'scanned_qty': line.scanned_qty,
            'difference': line.difference,
            'total_scans': self.scan_count,
        }

    def remove_line(self, line_id):
        """Xóa 1 line khỏi session"""
        self.ensure_one()
        if self.state != 'active':
            return {'success': False, 'error': 'Session đã đóng'}
            
        line = self.env['inventory.scan.line'].sudo().browse(line_id)
        if not line.exists() or line.session_id.id != self.id:
            return {'success': False, 'error': 'Line không hợp lệ'}
        
        line.unlink()
        
        return {
            'success': True,
            'product_count': self.product_count,
            'total_scans': self.scan_count,
        }

    def set_location(self, location_id):
        """Đổi location cho session"""
        self.ensure_one()
        if self.state != 'active':
            return {'success': False, 'error': 'Session đã đóng'}
        
        location = self.env['stock.location'].sudo().browse(location_id)
        if not location.exists():
            return {'success': False, 'error': 'Location không hợp lệ'}
        
        self.write({'location_id': location_id})
        
        # Cập nhật location cho tất cả lines chưa có location riêng
        self.line_ids.filtered(lambda l: not l.location_id).write({
            'location_id': location_id
        })
        
        return {
            'success': True,
            'location_id': location_id,
            'location_name': location.display_name,
        }

    def confirm_session(self):
        """
        Xác nhận session và áp dụng số liệu vào stock.quant.
        Tạo inventory adjustment lines.
        """
        self.ensure_one()
        if self.state != 'active':
            return {'success': False, 'error': 'Session đã đóng'}
        
        if not self.line_ids:
            return {'success': False, 'error': 'Không có sản phẩm nào để xác nhận'}

        Quant = self.env['stock.quant'].sudo()
        updated_count = 0
        
        for line in self.line_ids:
            location_id = line.location_id.id if line.location_id else self.location_id.id
            if not location_id:
                continue
                
            # Tìm hoặc tạo quant
            domain = [
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', location_id),
            ]
            if line.lot_id:
                domain.append(('lot_id', '=', line.lot_id.id))
            else:
                domain.append(('lot_id', '=', False))
                
            quant = Quant.search(domain, limit=1)
            
            if quant:
                quant.write({'inventory_quantity': line.scanned_qty})
            else:
                quant = Quant.create({
                    'product_id': line.product_id.id,
                    'location_id': location_id,
                    'lot_id': line.lot_id.id if line.lot_id else False,
                    'inventory_quantity': line.scanned_qty,
                })
            
            # Apply inventory adjustment
            quant.action_apply_inventory()
            updated_count += 1

        # Đánh dấu session confirmed
        self.write({
            'state': 'confirmed',
            'confirmed_time': fields.Datetime.now()
        })

        return {
            'success': True,
            'updated_count': updated_count,
            'message': f'Đã cập nhật {updated_count} sản phẩm vào kho',
        }

    def cancel_session(self):
        """Hủy session (không áp dụng dữ liệu)"""
        self.ensure_one()
        if self.state != 'active':
            return {'success': False, 'error': 'Session đã đóng'}
        
        self.write({'state': 'cancelled'})
        
        return {'success': True, 'message': 'Đã hủy phiên kiểm kê'}

    @api.model
    def cleanup_old_sessions(self):
        """Cron job: Xóa sessions cũ hơn 7 ngày và đã confirmed/cancelled"""
        cutoff = datetime.now() - timedelta(days=7)
        old_sessions = self.sudo().search([
            ('start_time', '<', cutoff),
            ('state', 'in', ['confirmed', 'cancelled'])
        ])
        old_sessions.unlink()
        return True

    @api.model
    def search_location(self, barcode):
        """Tìm location theo barcode"""
        location = self.env['stock.location'].sudo().search([
            '|',
            ('barcode', '=', barcode),
            ('name', 'ilike', barcode),
        ], limit=1)
        
        if location:
            return {
                'success': True,
                'location_id': location.id,
                'location_name': location.display_name,
            }
        return {'success': False, 'error': f'Không tìm thấy vị trí: {barcode}'}

    @api.model
    def search_product(self, barcode):
        """Tìm product theo barcode hoặc default_code"""
        product = self.env['product.product'].sudo().search([
            '|',
            ('barcode', '=', barcode),
            ('default_code', '=', barcode),
        ], limit=1)
        
        if product:
            return {
                'success': True,
                'product_id': product.id,
                'product_code': product.default_code or '',
                'product_name': product.display_name,
                'product_barcode': product.barcode or '',
                'uom_name': product.uom_id.name or 'Cái',
            }
        return {'success': False, 'error': f'Không tìm thấy sản phẩm: {barcode}'}

    @api.model
    def get_locations_for_dropdown(self, search_term='', limit=20):
        """Lấy danh sách locations cho dropdown"""
        domain = [('usage', '=', 'internal')]
        if search_term:
            domain.append(('complete_name', 'ilike', search_term))
        
        locations = self.env['stock.location'].sudo().search(domain, limit=limit)
        return [{
            'id': loc.id,
            'name': loc.display_name,
        } for loc in locations]
