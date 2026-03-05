# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import json
import math
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

    total_orders = fields.Integer(string='Tổng đơn', compute='_compute_stats')
    total_km = fields.Float(string='Tổng km', compute='_compute_stats', digits=(10, 1))
    priority_label = fields.Char(string='Mức ưu tiên', compute='_compute_stats')
    suggestion_text = fields.Text(string='Gợi ý', compute='_compute_stats')

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
                wiz.priority_label = '🔴 Cao — Đủ tải!'
            elif wiz.total_orders >= 5:
                wiz.priority_label = '🟡 Trung bình'
            else:
                wiz.priority_label = '🟢 Thấp — Gom thêm đơn'

            suggestions = []
            ready = len(selected.filtered(lambda l: l.stock_status == 'ready'))
            partial = len(selected.filtered(lambda l: l.stock_status == 'partial'))
            if wiz.total_orders >= 9 and ready == wiz.total_orders:
                suggestions.append('✅ Đủ tải + đủ hàng → Xuất phát!')
            elif wiz.total_orders < 9:
                suggestions.append(f'⏳ {wiz.total_orders} đơn, chờ gom thêm.')
            if partial > 0:
                suggestions.append(f'🟡 {partial} đơn đủ 1 phần.')
            wiz.suggestion_text = '\n'.join(suggestions) or '📋 Sẵn sàng.'

    @api.onchange('route_id')
    def _onchange_route_id(self):
        self.line_ids = [(5, 0, 0)]
        if not self.route_id:
            return
        lines = self.env['delivery.schedule.line'].search([
            ('route_id', '=', self.route_id.id),
            ('trip_id', '=', False),
            ('stock_status', 'in', ('ready', 'partial')),
        ], order='distance_km asc')
        self.line_ids = [(0, 0, {
            'schedule_line_id': l.id, 'selected': True,
        }) for l in lines]

    def _get_vehicle_capacity(self):
        if not self.vehicle_id:
            return 15
        name = (self.vehicle_id.model_id.name or '').lower()
        if 'xe máy' in name or 'xe_may' in name or 'honda' in name:
            return 5
        return 15

    def action_suggest_early_morning(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Chưa có đơn hàng nào.'))
        candidates = self.line_ids.sorted(key=lambda l: l.distance_km)
        keep = self.env['delivery.trip.wizard.line']
        for line in candidates:
            if line.stock_status in ('ready', 'partial') and len(keep) < 3:
                keep |= line
        (self.line_ids - keep).unlink()
        self.line_ids.write({'selected': True})
        self.departure_time = 'early_morning'
        return self._reload_wizard()

    def action_select_ready_only(self):
        self.ensure_one()
        self.line_ids.filtered(lambda l: l.stock_status != 'ready').unlink()
        self.line_ids.write({'selected': True})
        return self._reload_wizard()

    def action_create_trip(self):
        self.ensure_one()
        if not self.route_id:
            raise UserError(_('Vui lòng chọn Tuyến giao.'))
        selected = self.line_ids.filtered('selected')
        if not selected:
            raise UserError(_('Chưa chọn đơn hàng.'))

        trip = self.env['delivery.trip'].create({
            'date': self.date,
            'route_id': self.route_id.id,
            'driver_id': self.driver_id.id if self.driver_id else False,
            'vehicle_id': self.vehicle_id.id if self.vehicle_id else False,
            'departure_time': self.departure_time,
            'notes': self.notes,
        })
        selected.mapped('schedule_line_id').write({'trip_id': trip.id})
        _logger.info('Trip %s created with %d orders.', trip.name, len(selected))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.trip',
            'res_id': trip.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _reload_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.trip.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # =====================================================
    # Geocoding: Track-Asia API
    # =====================================================
    @staticmethod
    def _haversine(lat1, lng1, lat2, lng2):
        """Khoảng cách (km) giữa 2 toạ độ."""
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(dlng / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _geocode_address(self, query):
        """Geocode địa chỉ bằng Google Maps Places qua RapidAPI."""
        if not query:
            return None, None
        rapidapi_key = self.env['ir.config_parameter'].sudo().get_param(
            'ai_delivery_coordinator.rapidapi_key')
        if not rapidapi_key:
            _logger.warning('RapidAPI Key chưa cấu hình.')
            return None, None
        try:
            _logger.info('[Geocode] Searching: "%s"', query)
            resp = requests.post(
                'https://google-map-places-new-v2.p.rapidapi.com'
                '/v1/places:searchText',
                headers={
                    'Content-Type': 'application/json',
                    'X-Goog-FieldMask': (
                        'places.id,places.displayName,'
                        'places.formattedAddress,places.location'
                    ),
                    'x-rapidapi-host': (
                        'google-map-places-new-v2.p.rapidapi.com'
                    ),
                    'x-rapidapi-key': rapidapi_key,
                },
                json={
                    'textQuery': query,
                    'languageCode': 'vi',
                    'maxResultCount': 1,
                },
                timeout=15,
            )
            data = resp.json()
            places = data.get('places', [])
            if places:
                loc = places[0]['location']
                name = places[0].get('displayName', {}).get('text', '')
                lat = loc['latitude']
                lng = loc['longitude']
                _logger.info(
                    '[Geocode] ✓ "%s" → %s, %s (%s)',
                    query, lat, lng, name)
                return lat, lng
            _logger.warning('[Geocode] ✗ No result: "%s"', query)
        except Exception as e:
            _logger.warning('[Geocode] ✗ Error "%s": %s', query, e)
        return None, None

    def _get_warehouse_coords(self):
        """Lấy toạ độ kho xuất phát."""
        wh_id = self.env['ir.config_parameter'].sudo().get_param(
            'ai_delivery_coordinator.warehouse_id')
        if not wh_id:
            return None, None
        try:
            wh = self.env['stock.warehouse'].sudo().browse(int(wh_id))
            if wh.exists() and wh.partner_id:
                partner = wh.partner_id
                # Thử geocode địa chỉ kho nếu chưa có lat/lng
                addr = partner.street or partner.contact_address
                if addr:
                    lat, lng = self._geocode_address(addr)
                    return lat, lng
        except Exception as e:
            _logger.warning('Cannot get warehouse coords: %s', e)
        return None, None

    def _build_geocode_query(self, sl):
        """Tạo query geocode: tên công ty + địa chỉ."""
        parts = []
        if sl.partner_id and sl.partner_id.name:
            parts.append(sl.partner_id.name)
        if sl.delivery_address:
            parts.append(sl.delivery_address.strip())
        return ', '.join(parts)

    def _ensure_geocoded(self, schedule_lines):
        """Geocode tất cả line chưa có toạ độ hoặc đã đổi địa chỉ."""
        def needs_geocode(l):
            if not l.delivery_address:
                return False
            query = self._build_geocode_query(l)
            if not l.geocoded_query or l.geocoded_query != query:
                return True
            return False

        to_geocode = schedule_lines.filtered(needs_geocode)
        if not to_geocode:
            self._update_distances(schedule_lines)
            return

        # Nhóm theo (partner_name + address) tránh geocode trùng
        query_map = {}
        for sl in to_geocode:
            query = self._build_geocode_query(sl)
            if query:
                query_map.setdefault(query, []).append(sl)

        _logger.info('[Geocode] %d đơn cần geocode, %d query duy nhất',
                     len(to_geocode), len(query_map))
        for query, sls in query_map.items():
            lat, lng = self._geocode_address(query)
            for sl in sls:
                if lat and lng:
                    sl.sudo().write({
                        'delivery_lat': lat,
                        'delivery_lng': lng,
                        'geocoded_query': query,
                    })
                else:
                    sl.sudo().write({
                        'delivery_lat': 0.0,
                        'delivery_lng': 0.0,
                        'geocoded_query': query,
                    })

        # Cập nhật distance từ kho
        self._update_distances(schedule_lines)

    def _update_distances(self, schedule_lines):
        """Tính khoảng cách từ kho → mỗi điểm giao."""
        wh_lat, wh_lng = self._get_warehouse_coords()
        if not wh_lat or not wh_lng:
            return
        for sl in schedule_lines:
            if sl.delivery_lat and sl.delivery_lng:
                dist = self._haversine(
                    wh_lat, wh_lng, sl.delivery_lat, sl.delivery_lng)
                if abs(sl.distance_km - dist) > 0.5:
                    sl.sudo().write({'distance_km': round(dist, 1)})

    # =====================================================
    # Hybrid: Geocode + AI phân cụm
    # =====================================================
    def action_ai_suggest_groups(self):
        """Geocode → tính distance → AI phân cụm."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Chưa có đơn hàng nào.'))

        # Bước 1: Geocode + tính distance
        schedule_lines = self.line_ids.mapped('schedule_line_id')
        self._ensure_geocoded(schedule_lines)

        # Bước 2: API key và Cấu hình AI
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'ai_delivery_coordinator.openai_api_key')
        model_name = self.env['ir.config_parameter'].sudo().get_param(
            'ai_delivery_coordinator.openai_model_delivery', 'gpt-4o')
        ai_custom_prompt = self.env['ir.config_parameter'].sudo().get_param(
            'ai_delivery_coordinator.ai_custom_prompt', 
            'Bạn là chuyên gia logistics Việt Nam. Hãy phân tuyến tối ưu.'
        )
        if not api_key:
            raise UserError(_('Vui lòng cấu hình OpenAI API Key.'))

        today_str = fields.Date.context_today(self).strftime('%Y-%m-%d')
        capacity = self._get_vehicle_capacity()
        vehicle_label = 'xe máy' if capacity <= 5 else 'ô tô/xe tải'

        # Bước 3: Thu thập dữ liệu có toạ độ + distance
        order_data = []
        no_coords = 0
        for wl in self.line_ids:
            sl = wl.schedule_line_id
            so = sl.order_id
            commit_date = ''
            if so:
                if hasattr(so, 'commitment_date') and so.commitment_date:
                    commit_date = so.commitment_date.strftime('%Y-%m-%d')
                elif so.date_order:
                    commit_date = so.date_order.strftime('%Y-%m-%d')

            lat = sl.delivery_lat or 0
            lng = sl.delivery_lng or 0
            if not lat:
                no_coords += 1

            # Lấy thông tin chi tiết từng món hàng
            total_qty = 0
            items_desc = []
            if so:
                for line in so.order_line:
                    if line.product_uom_qty > 0:
                        total_qty += line.product_uom_qty
                        # Rút gọn tên SP để tiết kiệm token
                        prod_name = line.product_id.name or line.name or 'A'
                        if len(prod_name) > 30:
                            prod_name = prod_name[:27] + '...'
                        items_desc.append(f"{prod_name} x{line.product_uom_qty}")

            priority = ''
            if so:
                priority = getattr(so, 'priority', '')
                if not priority:
                    priority = getattr(so, 'x_priority', '')

            order_data.append({
                'id': wl.id,
                'order': so.name if so else '',
                'partner': sl.partner_id.name or '',
                'addr': (sl.delivery_address or '').replace('\n', ', '),
                'lat': round(lat, 5),
                'lng': round(lng, 5),
                'dist_km': round(sl.distance_km, 1),
                'stock': sl.stock_status or '',
                'htgh': (sl.order_htgh or '').strip(),
                'date': commit_date,
                'priority': priority,
                'items_qty': total_qty,
                'items_detail': ' | '.join(items_desc),
            })

        # Bước 4: AI với toạ độ + khoảng cách
        prompt = (
            f"{ai_custom_prompt}\n"
            f"Hôm nay: {today_str}\n"
            f"Phương tiện: {vehicle_label}.\n\n"
            "Dữ liệu có TOẠ ĐỘ GPS (lat/lng), KHOẢNG CÁCH từ kho (dist_km), "
            "tổng số lượng (items_qty), chi tiết hàng (items_detail) và MỨC ƯU TIÊN (priority).\n\n"
            f"CHỌN KHOẢNG {capacity} đơn cho 1 chuyến.\n"
            "Chỉ đạo: Ước lượng thể tích/khối lượng thực tế dựa vào 'items_detail'. (VD: 1000 cái ghế sẽ cồng kềnh hơn 1000 con ốc).\n"
            "Hãy CĂN CỨ VÀO ĐÓ ĐỂ QUYẾT ĐỊNH SỐ ĐƠN (chọn ít đơn lại nếu hàng quá to/nhiều).\n\n"
            "QUY TẮC BẮT BUỘC:\n"
            "★ KHÔNG BAO GIỜ tách đơn cùng PARTNER. "
            "Nếu chọn 1 đơn của 1 công ty → PHẢI chọn TẤT CẢ "
            "đơn của công ty đó. VD: Marshall 6 đơn → lấy cả 6.\n"
            "★ Nếu gom hết đơn cùng partner lại mà VƯỢT "
            f"{capacity} đơn hoặc xe đầy hàng → VẪN ĐƯỢC, ưu tiên gom đủ công ty.\n"
            "★ Đơn cùng toạ độ (< 0.05 độ) → chọn cùng\n\n"
            "ƯU TIÊN CHỌN ĐƠN:\n"
            "0. priority cao ('high', '1', v.v) → ƯU TIÊN HÀNG ĐẦU\n"
            "1. stock=ready → ưu tiên\n"
            "2. date gần/quá hạn → ưu tiên\n"
            "3. Đơn GẦN NHAU (lat/lng + dist_km) → gom\n"
            "4. htgh 'có gì giao nấy' → ưu tiên\n"
            "5. htgh 'chờ đủ hàng' + stock!=ready → BỎ QUA\n"
            "6. Tối ưu tuyến: chọn đơn cùng hướng\n\n"
            f"ĐƠN HÀNG ({len(order_data)} đơn):\n"
            f"{json.dumps(order_data, ensure_ascii=False)}\n\n"
            "TRẢ VỀ JSON:\n"
            "{\"thought_process\": \"<Vẽ 1 sơ đồ ASCII hoặc Bảng ASCII ngắn gọn minh hoạ việc gom cụm địa lý hoặc tải trọng. Dùng TÊN ĐƠN (order), không dùng id. Giải thích tóm tắt bằng bullet point và emoji, Giải thích cực kỳ ngắn gọn, dùng gạch đầu dòng và emoji để tóm tắt lý do gom chuyến>\",\n"
            "\"selected\": [<các id>], "
            "\"reason\": \"<Tóm tắt 1 câu ngắn>\"}\n"
            "CHỈ JSON."
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
            raise UserError(_('Lỗi AI: %s') % str(e))

        selected_ids = set(result.get('selected', []))
        reason = result.get('reason', '')
        thought_process = result.get('thought_process', '')
        if not selected_ids:
            raise UserError(_('AI không chọn được đơn nào.'))

        # Xóa đơn không chọn
        self.line_ids.filtered(lambda wl: wl.id not in selected_ids).unlink()
        self.line_ids.write({'selected': True})

        # Auto-detect route
        routes = self.line_ids.mapped('schedule_line_id.route_id')
        if len(routes) == 1 and routes:
            self.route_id = routes.id

        info = [
            f"🤖📍 AI + Geocode: chọn "
            f"{len(self.line_ids)}/{len(order_data)} đơn "
            f"({vehicle_label}, max {capacity}):",
            f"🧠 Tư duy AI:\n{thought_process}\n" if thought_process else "",
            f"📌 Kết luận: {reason}",
        ]
        if no_coords > 0:
            info.append(f"⚠ {no_coords} đơn không geocode được")
        self.notes = '\n'.join(info)
        return self._reload_wizard()

    def action_select_group(self):
        return self.action_ai_suggest_groups()

    # =====================================================
    # Google Maps View
    # =====================================================
    def action_view_map(self):
        """Mở Google Maps hiển thị tất cả điểm giao."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Chưa có đơn hàng nào.'))
        # Geocode nếu cần
        self._ensure_geocoded(self.line_ids.mapped('schedule_line_id'))

        # Dedup: loại bỏ điểm trùng toạ độ
        seen = set()
        points = []
        for wl in self.line_ids:
            sl = wl.schedule_line_id
            if sl.delivery_lat and sl.delivery_lng:
                key = f"{round(sl.delivery_lat, 5)},{round(sl.delivery_lng, 5)}"
                if key not in seen:
                    seen.add(key)
                    points.append(key)

        if not points:
            raise UserError(_('Không có toạ độ. Kiểm tra địa chỉ.'))

        # Thêm toạ độ kho làm điểm bắt đầu nếu có
        wh_lat, wh_lng = self._get_warehouse_coords()
        if wh_lat and wh_lng:
            points.insert(0, f"{round(wh_lat, 5)},{round(wh_lng, 5)}")

        if len(points) == 1:
            url = f'https://www.google.com/maps?q={points[0]}'
        else:
            url = 'https://www.google.com/maps/dir/' + '/'.join(points[:25])

        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }
