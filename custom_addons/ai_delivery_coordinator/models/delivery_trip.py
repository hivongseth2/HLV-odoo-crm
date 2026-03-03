# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class DeliveryTrip(models.Model):
    _name = 'delivery.trip'
    _description = 'Chuyến Giao Hàng'
    _order = 'date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Mã chuyến', required=True, copy=False, readonly=True, default='New')
    date = fields.Date(string='Ngày giao', required=True, default=fields.Date.context_today, tracking=True)
    route_id = fields.Many2one('delivery.route', string='Tuyến giao', required=True, tracking=True)

    driver_id = fields.Many2one('res.partner', string='Tài xế', tracking=True)
    vehicle_type = fields.Selection([
        ('xe_tai_lon', 'Xe tải lớn'),
        ('xe_van', 'Xe Van'),
        ('xe_may', 'Xe máy'),
    ], string='Loại xe', default='xe_van', tracking=True)

    departure_time = fields.Selection([
        ('early_morning', 'Sáng sớm (trước 10h)'),
        ('morning', 'Buổi sáng (10h-12h)'),
        ('afternoon', 'Buổi chiều (13h-17h)'),
    ], string='Ca xuất phát', default='morning', tracking=True)

    state = fields.Selection([
        ('draft', 'Nháp'),
        ('confirmed', 'Đã xác nhận'),
        ('in_progress', 'Đang giao'),
        ('done', 'Hoàn thành'),
        ('cancel', 'Hủy'),
    ], string='Trạng thái', default='draft', tracking=True)

    priority = fields.Selection([
        ('high', 'Cao (≥9 đơn)'),
        ('normal', 'Bình thường'),
        ('low', 'Thấp'),
    ], string='Ưu tiên', compute='_compute_priority', store=True)

    line_ids = fields.One2many('delivery.schedule.line', 'trip_id', string='Đơn hàng trong chuyến')
    total_orders = fields.Integer(string='Tổng đơn', compute='_compute_totals', store=True)
    total_km = fields.Float(string='Tổng km (ước tính)', compute='_compute_totals', store=True, digits=(10, 1))
    notes = fields.Text(string='Ghi chú')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('delivery.trip') or 'New'
        return super().create(vals_list)

    @api.depends('line_ids')
    def _compute_totals(self):
        for trip in self:
            trip.total_orders = len(trip.line_ids)
            trip.total_km = sum(trip.line_ids.mapped('distance_km'))

    @api.depends('total_orders')
    def _compute_priority(self):
        for trip in self:
            if trip.total_orders >= 9:
                trip.priority = 'high'
            elif trip.total_orders >= 5:
                trip.priority = 'normal'
            else:
                trip.priority = 'low'

    def action_confirm(self):
        for trip in self:
            if not trip.line_ids:
                raise UserError(_('Chuyến giao cần ít nhất 1 đơn hàng.'))
            trip.state = 'confirmed'

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        for trip in self:
            # Trả đơn về board (bỏ trip_id)
            trip.line_ids.write({'trip_id': False})
            trip.state = 'cancel'

    def action_draft(self):
        self.write({'state': 'draft'})
