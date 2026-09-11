import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from .dispatch_utils import normalize_name, parse_latlng

_logger = logging.getLogger(__name__)

# Nominatim giới hạn 1 request/giây. Cron chạy batch nhỏ để không bị chặn IP.
GEOCODE_BATCH_SIZE = 20


class HlvDeliveryPoint(models.Model):
    """Điểm giao vật lý — gom nhiều mã khách Odoo về MỘT địa điểm.

    Đây là model quan trọng nhất của module. Odoo sinh nhiều mã cho cùng một khách
    (351 mã = 176 khách thật). Nếu xếp chuyến theo partner_id thì cùng một nhà máy bị
    đếm thành 3 điểm và phá vỡ trần 8 điểm/chuyến. Mọi phép đếm điểm, mọi trần cụm,
    mọi thói quen khách đều gắn vào đây chứ không gắn vào res.partner.
    """

    _name = 'hlv.delivery.point'
    _description = 'Điểm giao hàng'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, index=True, tracking=True)
    map_name_key = fields.Char(
        string='Khoá so khớp', compute='_compute_map_name_key', store=True, index=True,
        help='Tên đã chuẩn hoá (bỏ dấu, bỏ tiền tố pháp nhân). Dùng để ghép khách Odoo với '
             'ghim bản đồ, và để re-import bản đồ không tạo điểm trùng — My Maps không xuất '
             'ID ổn định nên không thể khớp theo thứ tự.',
    )
    active = fields.Boolean(default=True)
    zone_id = fields.Many2one('hlv.delivery.zone', string='Cụm tuyến', index=True, tracking=True)
    warehouse_id = fields.Many2one(related='zone_id.warehouse_id', store=True, index=True)
    address = fields.Char(string='Địa chỉ', tracking=True)
    note = fields.Text(string='Ghi chú')

    partner_ids = fields.One2many(
        'res.partner', 'x_delivery_point_id', string='Mã khách Odoo',
    )
    partner_count = fields.Integer(compute='_compute_partner_count')

    profile_ids = fields.One2many(
        'hlv.delivery.partner.profile', 'point_id', string='Thói quen khách',
    )
    has_profile = fields.Boolean(compute='_compute_has_profile', store=True)

    # --- Toạ độ -------------------------------------------------------------
    # Không dùng partner_latitude/partner_longitude của base_geolocalize: toạ độ phải
    # nằm ở ĐIỂM (nhiều partner chung một điểm), không nằm ở từng mã khách.
    # base_geolocalize chỉ được dùng như service geocode (base.geocoder).
    latitude = fields.Float(string='Vĩ độ', digits=(10, 7), tracking=True)
    longitude = fields.Float(string='Kinh độ', digits=(10, 7), tracking=True)
    has_coords = fields.Boolean(compute='_compute_has_coords', store=True, string='Có toạ độ')
    geo_source = fields.Selection(
        [('map', 'Bản đồ My Maps'), ('geocode', 'Máy tra'), ('manual', 'Nhập tay')],
        string='Nguồn toạ độ',
    )
    geo_state = fields.Selection(
        [
            ('none', 'Chưa có'),
            ('pending_review', 'Chờ duyệt'),
            ('confirmed', 'Đã duyệt'),
            ('manual', 'Nhập tay'),
            ('failed', 'Máy không tìm được'),
        ],
        string='Trạng thái toạ độ', default='none', required=True, index=True, tracking=True,
    )
    geo_raw_result = fields.Text(string='Kết quả máy trả về')
    geo_checked_by_id = fields.Many2one('res.users', string='Người duyệt toạ độ', readonly=True)
    geo_checked_at = fields.Datetime(string='Duyệt lúc', readonly=True)
    geo_input = fields.Char(
        string='Nhập toạ độ',
        help='Dán thẳng dạng "10.78950, 106.99179" rồi bấm Lưu toạ độ nhập tay.',
    )
    map_url = fields.Char(compute='_compute_map_url', string='Mở Google Maps')

    # --- Bản đồ -------------------------------------------------------------
    map_layer = fields.Char(string='Lớp bản đồ')
    map_synced = fields.Boolean(
        string='Có trên bản đồ', default=False, index=True,
        help='False = khách chưa được ghim trên Google My Maps của router.',
    )
    map_last_synced_at = fields.Datetime(string='Đồng bộ bản đồ lúc', readonly=True)

    @api.depends('name')
    def _compute_map_name_key(self):
        for point in self:
            point.map_name_key = normalize_name(point.name)

    @api.depends('latitude', 'longitude')
    def _compute_has_coords(self):
        for point in self:
            point.has_coords = bool(point.latitude) and bool(point.longitude)

    @api.depends('profile_ids')
    def _compute_has_profile(self):
        for point in self:
            point.has_profile = bool(point.profile_ids)

    @api.depends('latitude', 'longitude')
    def _compute_map_url(self):
        for point in self:
            if point.latitude and point.longitude:
                point.map_url = 'https://www.google.com/maps?q=%s,%s' % (
                    point.latitude, point.longitude,
                )
            else:
                point.map_url = False

    @api.depends('partner_ids')
    def _compute_partner_count(self):
        grouped = {}
        if self.ids:
            for group in self.env['res.partner'].sudo()._read_group(
                [('x_delivery_point_id', 'in', self.ids)],
                groupby=['x_delivery_point_id'], aggregates=['__count'],
            ):
                grouped[group[0].id] = group[1]
        for point in self:
            point.partner_count = grouped.get(point.id, 0)

    # ------------------------------------------------------------------
    # Thói quen khách
    # ------------------------------------------------------------------
    def get_or_create_profile(self):
        """Trả về profile của điểm, tạo mới nếu chưa có (quan hệ 1-1)."""
        self.ensure_one()
        profile = self.profile_ids[:1]
        if not profile:
            profile = self.env['hlv.delivery.partner.profile'].create({'point_id': self.id})
        return profile

    def action_open_profile(self):
        self.ensure_one()
        profile = self.get_or_create_profile()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Thói quen khách — %s' % self.name,
            'res_model': 'hlv.delivery.partner.profile',
            'res_id': profile.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Geocode: máy tra trước, người duyệt sau
    # ------------------------------------------------------------------
    def _geocode_one(self):
        """Gọi base.geocoder cho 1 điểm. Không tự viết HTTP client."""
        self.ensure_one()
        address = (self.address or '').strip() or (self.name or '').strip()
        if not address:
            self.write({'geo_state': 'failed', 'geo_raw_result': 'Không có địa chỉ để tra.'})
            return False
        try:
            result = self.env['base.geocoder'].sudo().geo_find(address)
        except Exception as exc:  # provider lỗi/đổi API — không được làm gãy cron
            _logger.warning('Geocode lỗi cho điểm %s: %s', self.display_name, exc)
            self.write({'geo_state': 'failed', 'geo_raw_result': 'Lỗi khi tra: %s' % exc})
            return False
        if not result:
            self.write({
                'geo_state': 'failed',
                'geo_raw_result': 'Không tìm thấy toạ độ cho địa chỉ: %s' % address,
            })
            return False
        latitude, longitude = result[0], result[1]
        self.write({
            'latitude': latitude,
            'longitude': longitude,
            'geo_source': 'geocode',
            'geo_state': 'pending_review',
            'geo_raw_result': json.dumps(
                {'address': address, 'lat': latitude, 'lng': longitude},
                ensure_ascii=False,
            ),
        })
        return True

    @api.model
    def cron_geocode_pending(self, limit=GEOCODE_BATCH_SIZE):
        """Tra toạ độ cho các điểm chưa có. KHÔNG đụng tới điểm đã duyệt/nhập tay."""
        points = self.search([
            ('geo_state', '=', 'none'),
            ('active', '=', True),
        ], limit=limit)
        done = 0
        for point in points:
            if point._geocode_one():
                done += 1
        if points:
            _logger.info('Geocode: xử lý %s điểm, thành công %s', len(points), done)
        return done

    def action_geocode_now(self):
        """Nút tra lại toạ độ — cho phép chạy cả trên điểm đã failed."""
        for point in self:
            if point.geo_state == 'manual':
                # Toạ độ người nhập tay là nguồn đáng tin nhất, không đè lên.
                continue
            point._geocode_one()
        return True

    def action_confirm_geo(self):
        """Duyệt toạ độ máy đoán."""
        for point in self:
            if not point.has_coords:
                raise UserError('Điểm "%s" chưa có toạ độ để duyệt.' % point.name)
            point.write({
                'geo_state': 'confirmed',
                'geo_checked_by_id': self.env.user.id,
                'geo_checked_at': fields.Datetime.now(),
            })
        return True

    def action_save_manual_geo(self):
        """Lưu toạ độ dán tay từ ô geo_input."""
        for point in self:
            parsed = parse_latlng(point.geo_input)
            if not parsed:
                raise UserError(
                    'Không đọc được toạ độ "%s". Dán đúng dạng: 10.78950, 106.99179'
                    % (point.geo_input or '')
                )
            point.write({
                'latitude': parsed[0],
                'longitude': parsed[1],
                'geo_source': 'manual',
                'geo_state': 'manual',
                'geo_input': False,
                'geo_checked_by_id': self.env.user.id,
                'geo_checked_at': fields.Datetime.now(),
            })
        return True

    def action_mark_need_pin(self):
        """Đánh dấu cần ghim tay trên My Maps rồi re-import."""
        self.write({'geo_state': 'failed', 'map_synced': False})
        return True

    def action_open_gmaps(self):
        self.ensure_one()
        if not self.map_url:
            raise UserError('Điểm này chưa có toạ độ.')
        return {'type': 'ir.actions.act_url', 'url': self.map_url, 'target': 'new'}
