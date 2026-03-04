# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class DeliveryTrip(models.Model):
    _name = 'delivery.trip'
    _description = 'Chuyến Giao Hàng'
    _order = 'date desc, id desc'

    name = fields.Char(string='Mã chuyến', required=True, copy=False, readonly=True, default='New')
    date = fields.Date(string='Ngày giao', required=True, default=fields.Date.context_today)
    route_id = fields.Many2one('delivery.route', string='Tuyến giao', required=True)

    driver_id = fields.Many2one('res.partner', string='Tài xế')
    vehicle_id = fields.Many2one('fleet.vehicle', string='Xe')
    license_plate = fields.Char(related='vehicle_id.license_plate', string='Biển số', readonly=True)

    departure_time = fields.Selection([
        ('early_morning', 'Sáng sớm (trước 10h)'),
        ('morning', 'Buổi sáng (10h-12h)'),
        ('afternoon', 'Buổi chiều (13h-17h)'),
    ], string='Ca xuất phát', default='morning')

    priority = fields.Selection([
        ('high', 'Cao (≥9 đơn)'),
        ('normal', 'Bình thường'),
        ('low', 'Thấp'),
    ], string='Ưu tiên', compute='_compute_priority', store=True)

    line_ids = fields.One2many('delivery.schedule.line', 'trip_id', string='Đơn hàng trong chuyến')
    total_orders = fields.Integer(string='Tổng đơn', compute='_compute_totals', store=True)
    total_km = fields.Float(string='Tổng km (ước tính)', compute='_compute_totals', store=True, digits=(10, 1))
    batch_id = fields.Many2one('stock.picking.batch', string='Batch Picking', readonly=True)
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

    def action_create_batch(self):
        """Tạo stock.picking.batch từ các đơn hàng trong chuyến."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Chuyến giao cần ít nhất 1 đơn hàng.'))

        # Tìm phiếu xuất kho (stock.picking) liên quan đến các sale order
        sale_orders = self.line_ids.mapped('order_id')
        pickings = self.env['stock.picking'].search([
            ('origin', 'in', sale_orders.mapped('name')),
            ('picking_type_code', '=', 'outgoing'),
            ('state', 'in', ('assigned', 'confirmed', 'waiting')),
        ])

        if not pickings:
            raise UserError(_('Không tìm thấy phiếu xuất kho nào cho các đơn hàng này.'))

        batch = self.env['stock.picking.batch'].create({
            'name': f'BATCH/{self.name}',
            'picking_ids': [(6, 0, pickings.ids)],
            'user_id': self.driver_id.id if self.driver_id else False,
        })

        self.batch_id = batch.id
        # Bỏ chọn các đơn sau khi tạo batch
        self.line_ids.write({'is_selected': False})

        _logger.info('Batch %s created with %d pickings for trip %s.',
                      batch.name, len(pickings), self.name)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking.batch',
            'res_id': batch.id,
            'view_mode': 'form',
            'target': 'current',
        }
