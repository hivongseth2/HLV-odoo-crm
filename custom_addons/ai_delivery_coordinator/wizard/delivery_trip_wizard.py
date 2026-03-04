# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import json
import math
import requests
import time

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
    # Geocoding & Clustering
    # =====================================================
    @staticmethod
    def _haversine(lat1, lng1, lat2, lng2):
        """Khoảng cách (km) giữa 2 toạ độ."""
        R = 6371  # Bán kính Trái Đất
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(dlng / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _geocode_address(self, address):
        """Geocode 1 địa chỉ bằng Nominatim (OpenStreetMap)."""
        if not address:
            return None, None
        try:
            resp = requests.get(
                'https://nominatim.openstreetmap.org/search',
                params={
                    'q': address + ', Việt Nam',
                    'format': 'json',
                    'limit': 1,
                    'countrycodes': 'vn',
                },
                headers={'User-Agent': 'OdooDeliveryCoordinator/1.0'},
                timeout=10,
            )
            data = resp.json()
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
        except Exception as e:
            _logger.warning('Geocode failed for "%s": %s', address, e)
        return None, None

    def _ensure_geocoded(self, schedule_lines):
        """Đảm bảo tất cả line có lat/lng. Geocode nếu chưa có."""
        to_geocode = schedule_lines.filtered(
            lambda l: not l.delivery_lat and l.delivery_address)
        if not to_geocode:
            return

        # Nhóm theo địa chỉ để tránh geocode trùng
        addr_map = {}
        for sl in to_geocode:
            addr = (sl.delivery_address or '').strip()
            if addr:
                addr_map.setdefault(addr, []).append(sl)

        _logger.info('Geocoding %d unique addresses...', len(addr_map))
        for addr, lines_list in addr_map.items():
            lat, lng = self._geocode_address(addr)
            if lat and lng:
                for sl in lines_list:
                    sl.sudo().write({
                        'delivery_lat': lat,
                        'delivery_lng': lng,
                    })
            # Nominatim rate limit: 1 req/sec
            time.sleep(1.1)

    def _cluster_orders(self, orders_data, capacity, radius_km=30):
        """Phân cụm đơn hàng theo toạ độ.

        Args:
            orders_data: list of dict {id, lat, lng, partner_id, ...}
            capacity: max orders per cluster
            radius_km: bán kính cụm (km)

        Returns:
            list of clusters, mỗi cluster là list of order dicts.
            Cluster đầu tiên = tốt nhất (nhiều đơn, gần nhau).
        """
        if not orders_data:
            return []

        # Bước 1: nhóm theo partner_id (cùng công ty = cùng cụm)
        partner_groups = {}
        for o in orders_data:
            pid = o.get('partner_id', 0)
            partner_groups.setdefault(pid, []).append(o)

        # Bước 2: tạo "super-nodes" - mỗi node là 1 nhóm partner
        nodes = []
        for pid, group in partner_groups.items():
            # Centroid = trung bình lat/lng
            lats = [o['lat'] for o in group if o['lat']]
            lngs = [o['lng'] for o in group if o['lng']]
            if lats and lngs:
                clat = sum(lats) / len(lats)
                clng = sum(lngs) / len(lngs)
            else:
                clat, clng = 0, 0
            nodes.append({
                'partner_id': pid,
                'lat': clat,
                'lng': clng,
                'orders': group,
                'count': len(group),
                'assigned': False,
            })

        # Bước 3: Greedy clustering
        # Sắp xếp node theo số đơn giảm dần (ưu tiên gom nhóm lớn)
        nodes.sort(key=lambda n: -n['count'])
        clusters = []

        for node in nodes:
            if node['assigned']:
                continue
            # Tạo cụm mới từ node này
            cluster = list(node['orders'])
            node['assigned'] = True
            clat, clng = node['lat'], node['lng']

            # Tìm các node gần nhau để thêm vào cụm
            candidates = [
                n for n in nodes
                if not n['assigned'] and n['lat'] and n['lng']
            ]
            candidates.sort(
                key=lambda n: self._haversine(clat, clng, n['lat'], n['lng']))

            for cand in candidates:
                dist = self._haversine(clat, clng, cand['lat'], cand['lng'])
                if dist <= radius_km and len(cluster) + cand['count'] <= capacity:
                    cluster.extend(cand['orders'])
                    cand['assigned'] = True
                    # Cập nhật centroid
                    all_lats = [o['lat'] for o in cluster if o['lat']]
                    all_lngs = [o['lng'] for o in cluster if o['lng']]
                    if all_lats:
                        clat = sum(all_lats) / len(all_lats)
                        clng = sum(all_lngs) / len(all_lngs)

            clusters.append(cluster)

        # Sắp xếp cluster: nhiều đơn nhất trước
        clusters.sort(key=lambda c: -len(c))
        return clusters

    def action_ai_suggest_groups(self):
        """Phân cụm đơn hàng theo toạ độ + cùng công ty."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Chưa có đơn hàng nào.'))

        # Geocode tất cả đơn chưa có toạ độ
        schedule_lines = self.line_ids.mapped('schedule_line_id')
        self._ensure_geocoded(schedule_lines)

        # Chuẩn bị dữ liệu
        orders_data = []
        no_coords = 0
        for wl in self.line_ids:
            sl = wl.schedule_line_id
            lat = sl.delivery_lat or 0
            lng = sl.delivery_lng or 0
            if not lat:
                no_coords += 1
            orders_data.append({
                'wl_id': wl.id,
                'lat': lat,
                'lng': lng,
                'partner_id': sl.partner_id.id if sl.partner_id else 0,
                'partner_name': sl.partner_id.name or '',
                'stock': sl.stock_status or '',
            })

        capacity = self._get_vehicle_capacity()

        # Phân cụm
        clusters = self._cluster_orders(orders_data, capacity)

        if not clusters:
            raise UserError(_('Không thể phân cụm. Kiểm tra địa chỉ.'))

        # Chọn cụm đầu tiên (lớn nhất)
        best = clusters[0]
        best_ids = {o['wl_id'] for o in best}

        # Xóa đơn không thuộc cụm tốt nhất
        to_remove = self.line_ids.filtered(
            lambda wl: wl.id not in best_ids)
        to_remove.unlink()
        self.line_ids.write({'selected': True})

        # Auto-detect route
        routes = self.line_ids.mapped('schedule_line_id.route_id')
        if len(routes) == 1 and routes:
            self.route_id = routes.id

        # Tổng kết
        partners = set(o.get('partner_name', '') for o in best)
        partners_str = ', '.join(sorted(p for p in partners if p)[:5])

        info = [
            f"📍 Phân cụm: chọn {len(best)}/{len(orders_data)} đơn",
            f"🏢 Công ty: {partners_str}",
            f"📦 Sức chứa xe: {capacity} đơn",
        ]
        if no_coords > 0:
            info.append(f"⚠ {no_coords} đơn không geocode được (thiếu địa chỉ)")
        if len(clusters) > 1:
            other_summary = []
            for i, c in enumerate(clusters[1:], 2):
                names = set(o.get('partner_name', '') for o in c)
                other_summary.append(
                    f"  Cụm {i}: {len(c)} đơn "
                    f"({', '.join(sorted(n for n in names if n)[:3])})")
            info.append(f"📋 Còn {len(clusters)-1} cụm khác:")
            info.extend(other_summary[:4])

        self.notes = '\n'.join(info)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.trip.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_select_group(self):
        """Alias: chạy lại phân cụm với đơn còn lại."""
        return self.action_ai_suggest_groups()
