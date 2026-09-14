import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.hlv_geo_utils.tools.geo_text import normalize_name, parse_latlng

from ..services import pickup_maps, pickup_metrics
from ..services.pickup_address import partner_address_text, partner_phone

_logger = logging.getLogger(__name__)


class HlvPickupPoint(models.Model):
    """Điểm nhận hàng vật lý — gom nhiều mã nhà cung cấp Odoo về MỘT địa chỉ thật.

    Cùng bệnh với điểm giao bên ``hlv_delivery_dispatch``: Odoo sinh nhiều mã cho cùng một
    đối tác. Nếu đo định mức theo ``res.partner`` thì cùng một nhà máy bị tách thành ba tập
    mẫu, tập nào cũng quá ít để nói lên điều gì. Mọi con số "nhận hàng ở đây mất bao lâu"
    đều gắn vào ĐIỂM.
    """

    _name = 'hlv.pickup.point'
    _description = 'Điểm nhận hàng'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, index=True, tracking=True)
    map_name_key = fields.Char(
        string='Khoá so khớp', compute='_compute_map_name_key', store=True, index=True,
        help='Tên đã chuẩn hoá (bỏ dấu, bỏ tiền tố pháp nhân). Dùng để gom các mã nhà cung '
             'cấp viết tên khác nhau về cùng một điểm.',
    )
    active = fields.Boolean(default=True)
    address = fields.Char(string='Địa chỉ', tracking=True)
    note = fields.Text(string='Ghi chú', help='VD: vào cổng sau, phải báo trước 30 phút.')

    contact_name = fields.Char(string='Người liên hệ')
    contact_phone = fields.Char(string='Điện thoại')
    open_from = fields.Float(
        string='Nhận hàng từ', help='Giờ sớm nhất nhà cung cấp cho tới lấy hàng.',
    )
    open_to = fields.Float(string='Nhận hàng đến')

    partner_ids = fields.One2many(
        'res.partner', 'x_pickup_point_id', string='Mã nhà cung cấp',
    )
    partner_count = fields.Integer(compute='_compute_partner_count')

    # --- Toạ độ -------------------------------------------------------------
    latitude = fields.Float(string='Vĩ độ', digits=(10, 7), tracking=True)
    longitude = fields.Float(string='Kinh độ', digits=(10, 7), tracking=True)
    has_coords = fields.Boolean(compute='_compute_has_coords', store=True, string='Có toạ độ')
    google_place_id = fields.Char(
        string='Google Place ID', readonly=True, copy=False,
        help='Lưu lại để các lần gọi Directions/Distance Matrix sau không phải tra địa chỉ '
             'lại từ đầu — mỗi lần tra là một lượt tính tiền.',
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
    geo_source = fields.Selection(
        [
            ('geocode', 'Google tra'),
            ('manual', 'Nhập tay'),
            ('partner', 'Lấy từ liên hệ'),
        ],
        string='Nguồn toạ độ',
    )
    geo_raw_result = fields.Text(string='Kết quả máy trả về', readonly=True)
    geo_checked_by_id = fields.Many2one('res.users', string='Người duyệt', readonly=True)
    geo_checked_at = fields.Datetime(string='Duyệt lúc', readonly=True)
    geo_input = fields.Char(
        string='Nhập toạ độ',
        help='Dán thẳng dạng "10.78950, 106.99179" rồi bấm Lưu toạ độ nhập tay.',
    )
    map_url = fields.Char(compute='_compute_map_url', string='Mở Google Maps')

    # --- Định mức đo được ---------------------------------------------------
    stop_ids = fields.One2many('hlv.pickup.stop', 'point_id', string='Lượt đã tới')
    sample_count = fields.Integer(
        string='Số mẫu', compute='_compute_service_stats', store=True,
        help='Số lượt nhận hàng đã đo được mốc đầy đủ. Dưới 3 mẫu thì con số định mức chỉ '
             'để tham khảo.',
    )
    median_service_minutes = fields.Integer(
        string='Nhận hàng (phút)', compute='_compute_service_stats', store=True,
        help='Trung vị thời gian đứng tại điểm. Dùng trung vị vì một lần chờ 3 tiếng sẽ kéo '
             'trung bình lên và làm mọi dự kiến sau đó sai.',
    )
    max_service_minutes = fields.Integer(
        string='Lâu nhất (phút)', compute='_compute_service_stats', store=True,
    )
    last_visit_date = fields.Date(
        string='Lần tới gần nhất', compute='_compute_service_stats', store=True,
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Đã có điểm nhận hàng trùng tên.'),
    ]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('name')
    def _compute_map_name_key(self):
        for point in self:
            point.map_name_key = normalize_name(point.name)

    @api.depends('latitude', 'longitude')
    def _compute_has_coords(self):
        for point in self:
            point.has_coords = bool(point.latitude) and bool(point.longitude)

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
                [('x_pickup_point_id', 'in', self.ids)],
                groupby=['x_pickup_point_id'], aggregates=['__count'],
            ):
                grouped[group[0].id] = group[1]
        for point in self:
            point.partner_count = grouped.get(point.id, 0)

    @api.depends('stop_ids.state', 'stop_ids.service_minutes', 'stop_ids.is_estimated',
                 'stop_ids.arrived_at')
    def _compute_service_stats(self):
        """Định mức lấy từ lượt đã đi thật, KHÔNG tính lượt thiếu mốc.

        Một điểm bị quên bấm "đã tới" có ``service_minutes`` bằng 0; để lẫn vào sẽ kéo
        trung vị xuống và làm dự kiến của mọi chuyến sau ngắn hơn thực tế.
        """
        for point in self:
            done = point.stop_ids.filtered(
                lambda s: s.state == 'done' and not s.is_estimated and s.service_minutes
            )
            values = done.mapped('service_minutes')
            point.sample_count = len(values)
            point.median_service_minutes = int(round(pickup_metrics.median(values) or 0))
            point.max_service_minutes = max(values) if values else 0
            arrivals = point.stop_ids.filtered('arrived_at').mapped('arrived_at')
            point.last_visit_date = max(arrivals).date() if arrivals else False

    # ------------------------------------------------------------------
    # Gom nhà cung cấp về điểm
    # ------------------------------------------------------------------
    @api.model
    def find_or_create_for_partner(self, partner):
        """Điểm nhận hàng của một nhà cung cấp — tạo mới nếu chưa có.

        Thứ tự tìm: (1) điểm đã gán thẳng trên partner, (2) điểm có cùng khoá so khớp tên,
        (3) tạo mới từ địa chỉ của partner. Luôn gán ngược lại ``x_pickup_point_id`` để lần
        sau khỏi phải đoán.
        """
        partner = partner.sudo()
        if partner.x_pickup_point_id:
            return partner.x_pickup_point_id

        key = normalize_name(partner.name)
        point = self.search([('map_name_key', '=', key)], limit=1) if key else self.browse()
        if not point:
            point = self.create({
                # Tên là field bắt buộc và có ràng buộc duy nhất. Liên hệ không tên (dữ liệu
                # import lỗi) vẫn phải xếp chuyến được, nên đặt tên theo mã để không chặn.
                'name': partner.name or 'NCC #%s' % partner.id,
                'address': partner_address_text(partner),
                'contact_phone': partner_phone(partner),
                'latitude': partner.partner_latitude or 0.0,
                'longitude': partner.partner_longitude or 0.0,
                'geo_state': 'confirmed' if (
                    partner.partner_latitude and partner.partner_longitude
                ) else 'none',
                'geo_source': 'partner' if partner.partner_latitude else False,
            })
        partner.x_pickup_point_id = point.id
        return point

    # ------------------------------------------------------------------
    # Toạ độ
    # ------------------------------------------------------------------
    def action_geocode(self):
        """Hỏi Google toạ độ của địa chỉ. Kết quả vào trạng thái CHỜ DUYỆT, không dùng ngay.

        Địa chỉ khu công nghiệp hay bị Google trả về tâm của cả khu thay vì đúng nhà máy.
        Lấy thẳng vào dùng thì mọi cảnh báo "đứng sai chỗ" sau này đều sai.
        """
        for point in self:
            if not point.address:
                raise UserError('Điểm "%s" chưa có địa chỉ để tra.' % point.name)
            point._geocode_once()
        return True

    def _geocode_once(self):
        self.ensure_one()
        result = pickup_maps.geocode_address(self.env, self.address)
        if not result:
            self.write({'geo_state': 'failed', 'geo_raw_result': 'Không tìm thấy kết quả nào.'})
            return False
        self.write({
            'latitude': result['lat'],
            'longitude': result['lng'],
            'google_place_id': result.get('place_id') or False,
            'geo_source': 'geocode',
            'geo_state': 'pending_review',
            'geo_raw_result': result.get('formatted') or '',
        })
        return True

    def action_confirm_geo(self):
        self.write({
            'geo_state': 'confirmed',
            'geo_checked_by_id': self.env.user.id,
            'geo_checked_at': fields.Datetime.now(),
        })
        return True

    def action_save_manual_geo(self):
        for point in self:
            coords = parse_latlng(point.geo_input)
            if not coords:
                raise UserError(
                    'Không đọc được toạ độ "%s". Dán đúng dạng: 10.78950, 106.99179'
                    % (point.geo_input or '')
                )
            point.write({
                'latitude': coords[0],
                'longitude': coords[1],
                'geo_source': 'manual',
                'geo_state': 'manual',
                'geo_input': False,
                'geo_checked_by_id': self.env.user.id,
                'geo_checked_at': fields.Datetime.now(),
            })
        return True

    @api.model
    def cron_geocode_pending(self, limit=20):
        """Tra toạ độ cho các điểm chưa có. Batch nhỏ để không đốt quota Google trong một nhịp."""
        points = self.search([('geo_state', '=', 'none'), ('address', '!=', False)], limit=limit)
        for point in points:
            try:
                point._geocode_once()
            except UserError as error:
                # Hết quota / chưa khai key: dừng cả batch, lần chạy sau thử lại. Ghi
                # 'failed' cho từng điểm sẽ làm chúng không bao giờ được tra lại.
                _logger.warning('Dừng tra toạ độ điểm nhận hàng: %s', error)
                break
        return True

    def action_open_partners(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nhà cung cấp — %s' % self.name,
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('x_pickup_point_id', '=', self.id)],
            'context': {'default_x_pickup_point_id': self.id},
        }

    def action_open_stops(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lượt đã tới — %s' % self.name,
            'res_model': 'hlv.pickup.stop',
            'view_mode': 'list,form',
            'domain': [('point_id', '=', self.id)],
        }
