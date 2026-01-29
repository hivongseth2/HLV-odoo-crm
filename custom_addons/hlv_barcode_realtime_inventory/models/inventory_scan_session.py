# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta


class InventoryScanSession(models.Model):
    _name = 'inventory.scan.session'
    _description = 'Inventory Scan Session - Phiên quét kiểm kê'
    _order = 'start_time desc'

    name = fields.Char(string='Session ID', required=True, index=True, help='UUID từ frontend')
    device_id = fields.Char(string='Device Fingerprint', required=True, index=True, help='Để phân biệt các thiết bị dùng chung account')
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user, required=True)
    location_id = fields.Many2one('stock.location', string='Location', help='Vị trí được quét')
    
    state = fields.Selection([
        ('active', 'Đang quét'),
        ('confirmed', 'Đã xác nhận'),
        ('cancelled', 'Đã hủy')
    ], default='active', required=True, string='Trạng thái')
    
    line_ids = fields.One2many('inventory.scan.line', 'session_id', string='Scan Lines')
    scan_count = fields.Integer(string='Số lần quét', compute='_compute_scan_count', store=True)
    
    start_time = fields.Datetime(string='Bắt đầu', default=fields.Datetime.now, required=True)
    last_scan_time = fields.Datetime(string='Quét cuối')
    confirmed_time = fields.Datetime(string='Xác nhận lúc')
    
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('line_ids')
    def _compute_scan_count(self):
        for session in self:
            session.scan_count = len(session.line_ids)

    @api.model
    def register_scan(self, session_id, device_id, location_id, product_id, qty=1):
        """
        Real-time API: Ghi nhận 1 lần quét từ frontend.
        CẬP NHẬT TRỰC TIẾP vào stock.quant.inventory_quantity
        """
        if not session_id or not device_id:
            return {'success': False, 'error': 'Missing session_id or device_id'}
        
        if not location_id or not product_id:
            return {'success': False, 'error': 'Missing location_id or product_id'}

        # Tìm hoặc tạo session (để tracking audit trail)
        session = self.sudo().search([
            ('name', '=', session_id),
            ('state', '=', 'active')
        ], limit=1)
        
        if not session:
            session = self.sudo().create({
                'name': session_id,
                'device_id': device_id,
                'location_id': location_id,
                'user_id': self.env.user.id,
            })
        
        # Tạo scan line (audit trail)
        scan_line = self.env['inventory.scan.line'].sudo().create({
            'session_id': session.id,
            'product_id': product_id,
            'quantity': qty,
            'location_id': location_id,
            'scan_time': fields.Datetime.now(),
        })
        
        # ============================================================
        # REAL-TIME UPDATE: Cập nhật trực tiếp vào stock.quant
        # ============================================================
        Quant = self.env['stock.quant'].sudo()
        
        # Tìm quant hiện tại
        quant = Quant.search([
            ('product_id', '=', product_id),
            ('location_id', '=', location_id),
        ], limit=1)
        
        if quant:
            # Quant đã tồn tại → tăng inventory_quantity thêm qty
            new_qty = (quant.inventory_quantity or 0) + qty
            quant.write({'inventory_quantity': new_qty})
            current_qty = new_qty
        else:
            # Quant chưa tồn tại → tạo mới với inventory_quantity = qty
            quant = Quant.create({
                'product_id': product_id,
                'location_id': location_id,
                'inventory_quantity': qty,
            })
            current_qty = qty
        
        # Update session last_scan_time
        session.sudo().write({'last_scan_time': fields.Datetime.now()})
        
        # Lấy thông tin product để trả về
        product = self.env['product.product'].sudo().browse(product_id)
        
        return {
            'success': True,
            'session_id': session.id,
            'line_id': scan_line.id,
            'total_scans': len(session.line_ids),
            'quant_id': quant.id,
            'current_inventory_qty': current_qty,
            'product_name': product.display_name,
            'message': f'Đã cập nhật: {product.display_name} = {current_qty}'
        }

    @api.model
    def get_session_summary(self, session_id):
        """API: Lấy summary của session (để hiển thị UI indicator)"""
        session = self.sudo().search([('name', '=', session_id)], limit=1)
        if not session:
            return {'found': False}
        
        # Tính tổng theo product
        product_summary = {}
        for line in session.line_ids:
            prod_name = line.product_id.display_name
            if prod_name not in product_summary:
                product_summary[prod_name] = 0
            product_summary[prod_name] += line.quantity
        
        return {
            'found': True,
            'session_id': session.id,
            'device_id': session.device_id,
            'state': session.state,
            'total_scans': session.scan_count,
            'location': session.location_id.display_name if session.location_id else None,
            'products': product_summary,
            'last_scan': session.last_scan_time.isoformat() if session.last_scan_time else None,
        }

    def action_confirm_session(self):
        """Xác nhận session và merge vào inventory adjustment"""
        self.ensure_one()
        if self.state != 'active':
            return
        
        # TODO: Merge logic vào stock.quant hoặc inventory adjustment
        # Hiện tại chỉ đánh dấu là confirmed
        self.write({
            'state': 'confirmed',
            'confirmed_time': fields.Datetime.now()
        })
        
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def cleanup_old_sessions(self):
        """Cron job: Xóa sessions cũ hơn 24h và đã confirmed/cancelled"""
        cutoff = datetime.now() - timedelta(hours=24)
        old_sessions = self.sudo().search([
            ('start_time', '<', cutoff),
            ('state', 'in', ['confirmed', 'cancelled'])
        ])
        old_sessions.unlink()
        return True
