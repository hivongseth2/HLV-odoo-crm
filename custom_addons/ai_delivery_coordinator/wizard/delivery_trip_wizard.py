# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class DeliveryTripWizardLine(models.TransientModel):
    _name = 'delivery.trip.wizard.line'
    _description = 'Dòng wizard tạo chuyến'

    wizard_id = fields.Many2one('delivery.trip.wizard', string='Wizard', ondelete='cascade')
    schedule_line_id = fields.Many2one('delivery.schedule.line', string='Đơn hàng')
    order_id = fields.Many2one('sale.order', related='schedule_line_id.order_id', string='Mã đơn')
    partner_id = fields.Many2one('res.partner', related='schedule_line_id.partner_id', string='Khách hàng')
    delivery_address = fields.Char(related='schedule_line_id.delivery_address', string='Địa chỉ')
    stock_status = fields.Selection(related='schedule_line_id.stock_status', string='Tình trạng hàng')
    distance_km = fields.Float(related='schedule_line_id.distance_km', string='Km')
    selected = fields.Boolean(string='Chọn', default=True)


class DeliveryTripWizard(models.TransientModel):
    _name = 'delivery.trip.wizard'
    _description = 'Wizard Tạo Chuyến Giao Hàng'

    route_id = fields.Many2one('delivery.route', string='Tuyến giao')
    date = fields.Date(string='Ngày giao', required=True, default=fields.Date.context_today)
    driver_id = fields.Many2one('res.partner', string='Tài xế')
    vehicle_id = fields.Many2one('fleet.vehicle', string='Xe')
    departure_time = fields.Selection([
        ('early_morning', 'Sáng sớm (trước 10h)'),
        ('morning', 'Buổi sáng (10h-12h)'),
        ('afternoon', 'Buổi chiều (13h-17h)'),
    ], string='Ca xuất phát', default='morning')

    line_ids = fields.One2many('delivery.trip.wizard.line', 'wizard_id', string='Đơn hàng gợi ý')
    notes = fields.Text(string='Ghi chú')

    # Thống kê
    total_orders = fields.Integer(string='Tổng đơn được chọn', compute='_compute_stats')
    total_km = fields.Float(string='Tổng km', compute='_compute_stats', digits=(10, 1))
    priority_label = fields.Char(string='Mức ưu tiên', compute='_compute_stats')
    suggestion_text = fields.Text(string='Gợi ý AI', compute='_compute_stats')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        selected_ids = self.env.context.get('default_selected_line_ids', [])
        if selected_ids:
            lines = self.env['delivery.schedule.line'].browse(selected_ids).filtered(
                lambda l: not l.trip_id
            )
            if lines:
                # Auto-detect common route
                routes = lines.mapped('route_id')
                if len(routes) == 1:
                    res['route_id'] = routes.id
                wizard_lines = []
                for line in lines.sorted(key=lambda l: l.distance_km):
                    wizard_lines.append((0, 0, {
                        'schedule_line_id': line.id,
                        'selected': True,
                    }))
                res['line_ids'] = wizard_lines
        return res

    @api.depends('line_ids', 'line_ids.selected')
    def _compute_stats(self):
        for wiz in self:
            selected = wiz.line_ids.filtered('selected')
            wiz.total_orders = len(selected)
            wiz.total_km = sum(selected.mapped('distance_km'))

            # Ưu tiên
            if wiz.total_orders >= 9:
                wiz.priority_label = '🔴 Cao — Đủ tải, nên giao ngay!'
            elif wiz.total_orders >= 5:
                wiz.priority_label = '🟡 Trung bình'
            else:
                wiz.priority_label = '🟢 Thấp — Có thể gom thêm đơn'

            # Gợi ý
            suggestions = []
            ready_count = len(selected.filtered(lambda l: l.stock_status == 'ready'))
            partial_count = len(selected.filtered(lambda l: l.stock_status == 'partial'))
            shortage_count = len(selected.filtered(lambda l: l.stock_status in ('waiting', 'shortage')))

            if wiz.total_orders >= 9 and ready_count == wiz.total_orders:
                suggestions.append('✅ Đủ tải + đủ hàng → Xuất phát ngay!')
                suggestions.append('💡 Nên dùng xe tải lớn cho chuyến này.')
            elif wiz.total_orders < 9:
                suggestions.append(f'⏳ Chỉ có {wiz.total_orders} đơn, nên chờ gom thêm hoặc chọn 3 đơn gần nhất giao trước 10h.')
            if shortage_count > 0:
                suggestions.append(f'⚠ Có {shortage_count} đơn thiếu/chờ hàng — xem xét bỏ ra.')
            if partial_count > 0:
                suggestions.append(f'🟡 Có {partial_count} đơn chỉ đủ 1 phần.')

            wiz.suggestion_text = '\n'.join(suggestions) if suggestions else '📋 Sẵn sàng tạo chuyến.'

    @api.onchange('route_id')
    def _onchange_route_id(self):
        """Khi chọn tuyến, load đơn hàng chưa có chuyến thuộc tuyến đó."""
        self.line_ids = [(5, 0, 0)]
        if not self.route_id:
            return

        lines = self.env['delivery.schedule.line'].search([
            ('route_id', '=', self.route_id.id),
            ('trip_id', '=', False),
        ], order='distance_km asc')

        wizard_lines = []
        for line in lines:
            wizard_lines.append((0, 0, {
                'schedule_line_id': line.id,
                'selected': True,
            }))
        self.line_ids = wizard_lines

    def action_suggest_early_morning(self):
        """Gợi ý: chọn 3 đơn gần nhất cho chuyến sáng sớm."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Chưa có đơn hàng nào.'))

        # Bỏ chọn hết
        self.line_ids.write({'selected': False})

        # Chọn 3 đơn gần nhất có đủ hàng
        candidates = self.line_ids.sorted(key=lambda l: l.distance_km)
        count = 0
        for line in candidates:
            if line.stock_status in ('ready', 'partial') and count < 3:
                line.selected = True
                count += 1

        self.departure_time = 'early_morning'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.trip.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_select_ready_only(self):
        """Chỉ chọn đơn đủ hàng."""
        self.ensure_one()
        for line in self.line_ids:
            line.selected = line.stock_status == 'ready'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.trip.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_create_trip(self):
        """Tạo chuyến giao từ các đơn đã chọn."""
        self.ensure_one()
        if not self.route_id:
            raise UserError(_('Vui lòng chọn Tuyến giao trước khi tạo chuyến.'))
        selected = self.line_ids.filtered('selected')
        if not selected:
            raise UserError(_('Chưa chọn đơn hàng nào cho chuyến giao.'))

        trip = self.env['delivery.trip'].create({
            'date': self.date,
            'route_id': self.route_id.id,
            'driver_id': self.driver_id.id if self.driver_id else False,
            'vehicle_id': self.vehicle_id.id if self.vehicle_id else False,
            'departure_time': self.departure_time,
            'notes': self.notes,
        })

        # Gán trip_id cho các schedule lines
        schedule_line_ids = selected.mapped('schedule_line_id')
        schedule_line_ids.write({'trip_id': trip.id})

        _logger.info('Trip %s created with %d orders for route %s.',
                      trip.name, len(schedule_line_ids), self.route_id.name)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.trip',
            'res_id': trip.id,
            'view_mode': 'form',
            'target': 'current',
        }
