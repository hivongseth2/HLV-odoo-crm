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
    route = fields.Selection([
        ('nhon_trach', 'Nhơn Trạch'),
        ('long_thanh', 'Long Thành'),
        ('my_xuan_phu_my', 'Mỹ Xuân - Phú Mỹ'),
        ('noi_thanh', 'Nội Thành / Gần Công Ty'),
        ('khac', 'Khác')
    ], string='Tuyến giao', required=True)
    
    vehicle_type = fields.Selection([
        ('tai_lon', 'Xe tải lớn'),
        ('van_xe_may', 'Xe tải Van / Xe máy')
    ], string='Phương tiện', required=True)
    
    driver_name = fields.Char(string='Tài xế / Ghi chú')
    
    sale_order_ids = fields.Many2many('sale.order', string='Đơn hàng')
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('confirmed', 'Xác nhận'),
        ('done', 'Hoàn thành'),
        ('cancel', 'Hủy')
    ], string='Trạng thái', default='draft')
    note = fields.Text(string='Ghi chú từ AI')

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_done(self):
        self.write({'state': 'done'})
