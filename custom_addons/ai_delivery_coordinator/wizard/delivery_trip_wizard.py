# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import json
import requests

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
    picking_status = fields.Char(related='schedule_line_id.picking_status', string='Trạng thái kho')
    order_htgh = fields.Text(related='schedule_line_id.order_htgh', string='HTGH')
    distance_km = fields.Float(related='schedule_line_id.distance_km', string='Km')
    selected = fields.Boolean(string='Chọn', default=True)
    ai_group = fields.Char(string='Nhóm AI')


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
                lambda l: not l.trip_id and l.stock_status in ('ready', 'partial')
            )
            if lines:
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

            if wiz.total_orders >= 9:
                wiz.priority_label = '🔴 Cao — Đủ tải, nên giao ngay!'
            elif wiz.total_orders >= 5:
                wiz.priority_label = '🟡 Trung bình'
            else:
                wiz.priority_label = '🟢 Thấp — Có thể gom thêm đơn'

            suggestions = []
            ready_count = len(selected.filtered(lambda l: l.stock_status == 'ready'))
            partial_count = len(selected.filtered(lambda l: l.stock_status == 'partial'))

            if wiz.total_orders >= 9 and ready_count == wiz.total_orders:
                suggestions.append('✅ Đủ tải + đủ hàng → Xuất phát ngay!')
            elif wiz.total_orders < 9:
                suggestions.append(f'⏳ Chỉ có {wiz.total_orders} đơn, nên chờ gom thêm.')
            if partial_count > 0:
                suggestions.append(f'🟡 Có {partial_count} đơn chỉ đủ 1 phần.')

            wiz.suggestion_text = '\n'.join(suggestions) if suggestions else '📋 Sẵn sàng tạo chuyến.'

    @api.onchange('route_id')
    def _onchange_route_id(self):
        """Khi chọn tuyến, load đơn đủ/1 phần hàng chưa có chuyến."""
        self.line_ids = [(5, 0, 0)]
        if not self.route_id:
            return

        lines = self.env['delivery.schedule.line'].search([
            ('route_id', '=', self.route_id.id),
            ('trip_id', '=', False),
            ('stock_status', 'in', ('ready', 'partial')),
        ], order='distance_km asc')

        wizard_lines = []
        for line in lines:
            wizard_lines.append((0, 0, {
                'schedule_line_id': line.id,
                'selected': True,
            }))
        self.line_ids = wizard_lines

    def _get_vehicle_capacity(self):
        """Số đơn tối đa theo loại xe."""
        if not self.vehicle_id:
            return 15
        name = (self.vehicle_id.model_id.name or '').lower()
        if 'xe máy' in name or 'xe_may' in name or 'honda' in name:
            return 5
        return 15

    def action_suggest_early_morning(self):
        """Gợi ý: chọn 3 đơn gần nhất cho chuyến sáng sớm."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Chưa có đơn hàng nào.'))

        # Xóa đơn xa, giữ 3 đơn gần nhất đủ hàng
        candidates = self.line_ids.sorted(key=lambda l: l.distance_km)
        keep = self.env['delivery.trip.wizard.line']
        for line in candidates:
            if line.stock_status in ('ready', 'partial') and len(keep) < 3:
                keep |= line

        to_remove = self.line_ids - keep
        to_remove.unlink()
        self.line_ids.write({'selected': True})
        self.departure_time = 'early_morning'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.trip.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_select_ready_only(self):
        """Chỉ giữ đơn đủ hàng, xóa đơn partial."""
        self.ensure_one()
        to_remove = self.line_ids.filtered(
            lambda l: l.stock_status != 'ready')
        to_remove.unlink()
        self.line_ids.write({'selected': True})
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

    # =====================================================
    # AI Chọn đơn tối ưu cho 1 chuyến
    # =====================================================
    def action_ai_suggest_groups(self):
        """AI tự chọn đơn tốt nhất cho 1 chuyến giao ngay."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Chưa có đơn hàng nào.'))

        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'ai_delivery_coordinator.openai_api_key')
        model_name = self.env['ir.config_parameter'].sudo().get_param(
            'ai_delivery_coordinator.openai_model_delivery', 'gpt-4o')
        if not api_key:
            raise UserError(_(
                'Vui lòng cấu hình OpenAI API Key.'))

        # Thu thập dữ liệu
        order_data = []
        today_str = fields.Date.context_today(self).strftime('%Y-%m-%d')
        for wl in self.line_ids:
            sl = wl.schedule_line_id
            so = sl.order_id
            commit_date = ''
            if so:
                if hasattr(so, 'commitment_date') and so.commitment_date:
                    commit_date = so.commitment_date.strftime('%Y-%m-%d')
                elif so.date_order:
                    commit_date = so.date_order.strftime('%Y-%m-%d')

            order_data.append({
                'id': wl.id,
                'order': so.name if so else '',
                'partner': sl.partner_id.name or '',
                'addr': (sl.delivery_address or '').replace('\n', ', '),
                'picking': sl.picking_status or '',
                'stock': sl.stock_status or '',
                'htgh': (sl.order_htgh or '').strip(),
                'date': commit_date,
                'km': sl.distance_km or 0,
            })

        capacity = self._get_vehicle_capacity()
        vehicle_label = 'xe máy' if capacity <= 5 else 'ô tô/xe tải'

        prompt = (
            "Bạn là chuyên gia logistics Việt Nam.\n"
            f"Hôm nay: {today_str}\n"
            f"Phương tiện: {vehicle_label} "
            f"(tối đa {capacity} đơn/chuyến).\n\n"
            "TỪ DANH SÁCH BÊN DƯỚI, "
            f"CHỌN TỐI ĐA {capacity} đơn TỐT NHẤT "
            "cho 1 chuyến giao NGAY BÂY GIỜ.\n\n"
            "QUY TẮC BẮT BUỘC:\n"
            "★ KHI CHỌN 1 ĐƠN CỦA 1 CÔNG TY (partner), "
            "PHẢI CHỌN TẤT CẢ ĐƠN CỦA CÔNG TY ĐÓ. "
            "VD: Marshall có 3 đơn → chọn cả 3, "
            "KHÔNG được chọn 1 bỏ 2.\n"
            "★ Đơn cùng ĐỊA CHỈ giao (addr giống nhau) "
            "→ BẮT BUỘC chọn cùng nhau.\n\n"
            "ƯU TIÊN (theo thứ tự):\n"
            "1. stock=ready (đủ hàng) → chọn trước\n"
            "2. Đơn GẤP: date gần/quá hạn → chọn trước\n"
            "3. Đơn cùng KHU VỰC (quận/huyện/tỉnh) → gom chung\n"
            "4. htgh chứa 'có gì giao nấy' → ưu tiên\n"
            "5. htgh chứa 'chờ đủ hàng' + stock!=ready → BỎ QUA\n"
            "6. stock=partial + htgh rỗng → vẫn chọn được\n\n"
            f"ĐƠN HÀNG ({len(order_data)} đơn):\n"
            f"{json.dumps(order_data, ensure_ascii=False)}\n\n"
            "TRẢ VỀ JSON DUY NHẤT:\n"
            "{\"selected\": [<danh sách id đã chọn>], "
            "\"reason\": \"<lý do ngắn gọn>\"}\n"
            "CHỈ JSON, không giải thích."
        )

        try:
            resp = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': model_name,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0.2,
                },
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json()['choices'][0]['message']['content']

            content = content.strip()
            if content.startswith('```'):
                content = content.split('\n', 1)[1]
                content = content.rsplit('```', 1)[0]
            result = json.loads(content)
        except Exception as e:
            _logger.error('AI Suggest Error: %s', e)
            raise UserError(_('Lỗi khi gọi AI: %s') % str(e))

        selected_ids = set(result.get('selected', []))
        reason = result.get('reason', '')

        if not selected_ids:
            raise UserError(_('AI không chọn được đơn nào.'))

        # XÓA đơn không được chọn khỏi wizard
        to_remove = self.line_ids.filtered(
            lambda wl: wl.id not in selected_ids)
        to_remove.unlink()

        # Select tất cả còn lại
        self.line_ids.write({'selected': True})

        # Auto-detect route
        routes = self.line_ids.mapped('schedule_line_id.route_id')
        if len(routes) == 1 and routes:
            self.route_id = routes.id

        self.notes = (
            f"🤖 AI đã chọn {len(self.line_ids)}/{len(order_data)} đơn "
            f"({vehicle_label}, max {capacity}):\n"
            f"{reason}"
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.trip.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_select_group(self):
        """Alias: chạy lại AI với đơn còn lại."""
        return self.action_ai_suggest_groups()
