# -*- coding: utf-8 -*-
from odoo import models, fields, api

class DeliveryCoordinatorReport(models.TransientModel):
    _name = 'delivery.coordinator.report'
    _description = 'Báo cáo tổng hợp tình trạng giao hàng'

    date = fields.Date('Ngày báo cáo')
    total_pending_orders = fields.Integer('Tổng đơn chờ giao')
    orders_ready_to_ship = fields.Integer('Đơn đủ hàng để xếp lịch')
    
    orders_insufficient_stock_text = fields.Text('Đơn không đủ hàng (Bỏ qua)')
    orders_backlog_text = fields.Text('Đơn nợ đọng từ các ngày trước')

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}
