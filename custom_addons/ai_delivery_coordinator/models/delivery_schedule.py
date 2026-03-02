# -*- coding: utf-8 -*-
from odoo import models, fields

class DeliveryRoute(models.Model):
    _name = 'delivery.route'
    _description = 'Delivery Route'

    name = fields.Char(string='Tên tuyến', required=True)
    description = fields.Text(string='Mô tả')

class DeliverySchedule(models.Model):
    _name = 'delivery.schedule'
    _description = 'Delivery Schedule from AI'
    _order = 'date desc, id desc'

    name = fields.Char(string='Mã chuyến', required=True, copy=False, readonly=True, default=lambda self: 'New')
    date = fields.Date(string='Ngày giao', required=True, default=fields.Date.context_today)
    route = fields.Char(string='Tuyến giao hàng', required=True)
    warehouse_code = fields.Char(string='Kho xuất')
    vehicle_type = fields.Selection([
        ('tai_lon', 'Xe tải lớn'),
        ('van_xe_may', 'Xe tải Van / Xe máy')
    ], string='Phương tiện', required=True)
    driver_name = fields.Char(string='Tài xế / Ghi chú', help="Tên tài xế hoặc mô tả phương tiện phụ")
    
    line_ids = fields.One2many('delivery.schedule.line', 'schedule_id', string='Chi tiết đơn hàng')
    
    session = fields.Selection([
        ('morning', 'Sáng'),
        ('afternoon', 'Chiều'),
        ('evening', 'Tối'),
        ('other', 'Khác')
    ], string='Phiên giao hàng', default='morning', required=True)
    
    note = fields.Text(string='Ghi chú từ AI')

    def action_create_batch_picking(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Lịch trình không có đơn hàng nào."))
            
        picking_ids = []
        for line in self.line_ids:
            # Lấy các phiếu kho (outgoing/pick/pack) của đơn sale chưa hoàn thành
            pickings = line.order_id.picking_ids.filtered(lambda p: p.state not in ['done', 'cancel'])
            picking_ids.extend(pickings.ids)
            
        if not picking_ids:
            raise UserError(_("Không tìm thấy phiếu lấy hàng/giao hàng nào hợp lệ cho các đơn hàng này."))
            
        # Create a new batch picking
        batch_vals = {
            'user_id': self.env.user.id,
            'picking_ids': [(6, 0, picking_ids)],
            # Add any other helpful fields here, for example picking_type_id if required by user config
        }
        batch = self.env['stock.picking.batch'].create(batch_vals)
        
        return {
            'name': _('Batch Giao Hàng'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking.batch',
            'res_id': batch.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_google_map(self):
        self.ensure_one()
        import urllib.parse
        
        # Get origin (warehouse)
        origin = self.warehouse_code or ''
        warehouse = self.env['stock.warehouse'].search([('code', '=', self.warehouse_code)], limit=1)
        if warehouse and warehouse.partner_id.contact_address:
            origin = warehouse.partner_id.contact_address.replace('\n', ', ')
            
        # Get destinations (delivery addresses)
        addresses = []
        for line in self.line_ids:
            if line.order_id.partner_shipping_id:
                addr = line.order_id.partner_shipping_id.contact_address
                if addr:
                    addresses.append(addr.replace('\n', ', '))
                    
        if not addresses:
            raise UserError(str("Không có địa chỉ giao hàng nào trong lịch trình này."))
            
        # Google Maps Dir URL expects: /dir/?api=1&origin=...&destination=...&waypoints=...|...
        # We set origin as warehouse, destination as last address, and waypoints as the rest.
        destination = addresses[-1]
        waypoints = addresses[:-1]
        
        base_url = "https://www.google.com/maps/dir/?api=1"
        url_params = {
            'origin': origin,
            'destination': destination
        }
        if waypoints:
            url_params['waypoints'] = '|'.join(waypoints)
            
        full_url = f"{base_url}&{urllib.parse.urlencode(url_params)}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': full_url,
            'target': 'new',
        }

class DeliveryScheduleLine(models.Model):
    _name = 'delivery.schedule.line'
    _description = 'Chi tiết đơn hàng trong Lịch trình'

    schedule_id = fields.Many2one('delivery.schedule', string='Lịch trình', required=True, ondelete='cascade')
    order_id = fields.Many2one('sale.order', string='Đơn hàng', required=True)
    partner_id = fields.Many2one(related='order_id.partner_id', string='Khách hàng', readonly=True)
    commitment_date = fields.Datetime(related='order_id.commitment_date', string='Ngày hẹn giao', readonly=True)
    
    stock_status = fields.Selection([
        ('ready', 'Đủ hàng'),
        ('waiting', 'Chờ hàng về'),
        ('shortage', 'Thiếu hàng')
    ], string='Tình trạng hàng')
    
    ai_strategy = fields.Char(string='Chiến lược / Ghi chú AI')
