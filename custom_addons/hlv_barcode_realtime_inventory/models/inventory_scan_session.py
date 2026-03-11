from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class InventoryScanSession(models.Model):
    _name = 'inventory.scan.session'
    _description = 'Inventory Scan Session'
    
    name = fields.Char(string='Mã phiên', required=True, copy=False, readonly=True, default='New')
    user_id = fields.Many2one('res.users', string='Người quét', default=lambda self: self.env.user, required=True)
    device_id = fields.Char(string='Device ID', help="Browser fingerprint or device identifier")
    
    start_time = fields.Datetime(string='Bắt đầu', default=fields.Datetime.now)
    last_scan_time = fields.Datetime(string='Quét lần cuối')
    confirmed_time = fields.Datetime(string='Xác nhận lúc')
    
    location_id = fields.Many2one('stock.location', string='Vị trí kho', domain=[('usage', '=', 'internal')])
    
    line_ids = fields.One2many('inventory.scan.line', 'session_id', string='Chi tiết quét')
    
    state = fields.Selection([
        ('active', 'Đang quét'),
        ('confirmed', 'Đã xác nhận'),
        ('cancelled', 'Đã hủy')
    ], string='Trạng thái', default='active')
    
    scan_count = fields.Integer(string='Tổng lượt quét', compute='_compute_stats', store=True)
    product_count = fields.Integer(string='Số sản phẩm', compute='_compute_stats', store=True)

    @api.depends('line_ids', 'line_ids.scanned_qty')
    def _compute_stats(self):
        for session in self:
            session.product_count = len(session.line_ids)
            session.scan_count = sum(session.line_ids.mapped('scanned_qty'))

    @api.model_create_multi
    def create(self, vals_list):
        """Override batch create for Odoo 18 compatibility"""
        # Generate sequence numbers for new records
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('inventory.scan.session') or 'SCAN'
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # API Methods for OWL Component
    # -------------------------------------------------------------------------

    @api.model
    def get_or_create_active_session(self, device_id, location_id=None):
        """Khôi phục phiên làm việc cũ hoặc tạo mới"""
        domain = [
            ('user_id', '=', self.env.user.id),
            ('state', '=', 'active'),
            ('device_id', '=', device_id)
        ]
        
        # Nếu có location, ưu tiên tìm session của location đó
        if location_id:
            domain.append(('location_id', '=', location_id))
            
        session = self.search(domain, limit=1, order='last_scan_time desc')
        
        if not session:
            # Tạo session mới nếu không tìm thấy
            vals = {
                'user_id': self.env.user.id,
                'device_id': device_id,
                'start_time': fields.Datetime.now(),
                'state': 'active'
            }
            if location_id:
                vals['location_id'] = location_id
                
            session = self.create(vals)
            
        return session._get_session_data()

    def _get_session_data(self):
        self.ensure_one()
        return {
            'success': True,
            'session_id': self.id,
            'name': self.name,
            'location_id': self.location_id.id or False,
            'location_name': self.location_id.display_name or '',
            'product_count': self.product_count,
            'scan_count': self.scan_count,
            'lines': self._get_lines_data()
        }

    def _get_lines_data(self):
        return [{
            'id': line.id,
            'product_id': line.product_id.id,
            'product_name': line.product_id.name,
            'product_code': line.product_id.default_code,
            'uom_name': line.product_id.uom_id.name,
            'scanned_qty': line.scanned_qty,
            'theoretical_qty': line.theoretical_qty,
            'difference': line.difference,
            'location_id': line.location_id.id,
            'lot_id': line.lot_id.id,
            'package_id': line.package_id.id,
        } for line in self.line_ids.sorted(key=lambda l: l.create_date, reverse=True)]

    @api.model
    def register_scan(self, session_id, product_id, location_id, qty=1, lot_id=False, package_id=False):
        """Xử lý mỗi lần quét barcode"""
        session = self.browse(session_id)
        if not session.exists() or session.state != 'active':
            return {'success': False, 'error': 'Phiên làm việc không hợp lệ'}
            
        # Tìm scan line đã có
        domain = [
            ('session_id', '=', session_id),
            ('product_id', '=', product_id),
            ('location_id', '=', location_id)
        ]
        if lot_id:
            domain.append(('lot_id', '=', lot_id))
        else:
            domain.append(('lot_id', '=', False))
            
        if package_id:
            domain.append(('package_id', '=', package_id))
        else:
            domain.append(('package_id', '=', False))
            
        line = self.env['inventory.scan.line'].search(domain, limit=1)
        
        if line:
            line.scanned_qty += qty
        else:
            # Lấy tồn kho lý thuyết
            quant_domain = [
                ('product_id', '=', product_id),
                ('location_id', '=', location_id)
            ]
            if lot_id:
                quant_domain.append(('lot_id', '=', lot_id))
            if package_id:
                quant_domain.append(('package_id', '=', package_id))
                
            quants = self.env['stock.quant'].search(quant_domain)
            theoretical_qty = sum(quants.mapped('quantity'))
            
            line = self.env['inventory.scan.line'].create({
                'session_id': session_id,
                'product_id': product_id,
                'location_id': location_id,
                'lot_id': lot_id,
                'package_id': package_id,
                'scanned_qty': qty,
                'theoretical_qty': theoretical_qty
            })

        # Update Stock Quant Real-time (Optional - tùy yêu cầu business)
        # Ở đây chúng ta CHƯA update stock.quant, chỉ lưu vào session
        # Khi Confirm Session mới apply inventory adjustment
        
        session.write({'last_scan_time': fields.Datetime.now()})
        
        return {
            'success': True,
            'line_id': line.id,
            'product_id': line.product_id.id,
            'product_name': line.product_id.name,
            'product_code': line.product_id.default_code,
            'uom_name': line.product_id.uom_id.name,
            'scanned_qty': line.scanned_qty,
            'theoretical_qty': line.theoretical_qty,
            'difference': line.difference,
            'product_count': session.product_count,
            'total_scans': session.scan_count
        }

    @api.model
    def update_line_qty(self, session_id, line_id, new_qty):
        line = self.env['inventory.scan.line'].browse(line_id)
        if line.session_id.id != session_id:
            return {'success': False, 'error': 'Lỗi bảo mật'}
            
        line.write({'scanned_qty': new_qty})
        
        return {
            'success': True,
            'scanned_qty': line.scanned_qty,
            'difference': line.difference,
            'total_scans': line.session_id.scan_count
        }

    @api.model
    def remove_line(self, session_id, line_id):
        line = self.env['inventory.scan.line'].browse(line_id)
        if line.session_id.id != session_id:
            return {'success': False, 'error': 'Lỗi bảo mật'}
            
        session = line.session_id
        line.unlink()
        
        return {
            'success': True,
            'product_count': session.product_count,
            'total_scans': session.scan_count
        }
    
    @api.model
    def set_location(self, session_id, location_id):
        session = self.browse(session_id)
        if session.exists():
            session.write({'location_id': location_id})
            return {'success': True}
        return {'success': False}

    def confirm_session(self):
        """Confirm session and apply stock inventory adjustment"""
        self.ensure_one()
        if self.state != 'active':
            return {'success': False, 'error': _('Session không hợp lệ')}
            
        # 1. Tạo Inventory Adjustment (Stock Quant update)
        # Loop qua các line và update quantity
        for line in self.line_ids:
            # Tìm hoặc tạo stock.quant
            quant = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', line.location_id.id),
                ('lot_id', '=', line.lot_id.id or False),
                ('package_id', '=', line.package_id.id or False),
            ], limit=1)
            
            if not quant:
                quant = self.env['stock.quant'].create({
                    'product_id': line.product_id.id,
                    'location_id': line.location_id.id,
                    'lot_id': line.lot_id.id or False,
                    'package_id': line.package_id.id or False,
                    'inventory_quantity': line.scanned_qty, # Set inventory quantity
                })
            else:
                quant.inventory_quantity = line.scanned_qty
                
            # Apply inventory adjustment
            try:
                quant.action_apply_inventory()
            except Exception as e:
                _logger.error(f"Error applying inventory for product {line.product_id.name}: {str(e)}")
                # Có thể return lỗi hoặc continue tùy chiến lược
        
        self.write({
            'state': 'confirmed',
            'confirmed_time': fields.Datetime.now()
        })
        
        return {'success': True, 'message': _('Đã cập nhật tồn kho thành công!')}

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
                ('name', '=', barcode), 
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
            'product_barcode': product.barcode or '',
            'uom_name': product.uom_id.name or 'Cái',
        }

    @api.model
    def get_locations_for_dropdown(self, search_term='', limit=20):
        """Lấy danh sách locations cho dropdown (không giới hạn warehouse)"""
        domain = [('usage', '=', 'internal')]
        if search_term:
            domain += [('complete_name', 'ilike', search_term)]
        
        locations = self.env['stock.location'].search_read(
            domain, 
            ['id', 'complete_name'], 
            limit=limit, 
            order='complete_name asc'
        )
        return [{'id': l['id'], 'name': l['complete_name']} for l in locations]
        
    @api.model
    def search_product_suggestions(self, search_term, limit=10):
        """Cho dropdown gợi ý tìm kiếm sản phẩm"""
        domain = [
            '|', '|',
            ('barcode', 'ilike', search_term),
            ('default_code', 'ilike', search_term),
            ('name', 'ilike', search_term)
        ]
        products = self.env['product.product'].search_read(
            domain,
            ['id', 'display_name', 'default_code', 'barcode'],
            limit=limit
        )
        return products
