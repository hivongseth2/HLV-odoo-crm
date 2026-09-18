import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.hlv_geo_utils.tools.geo_text import parse_latlng
from odoo.addons.hlv_vtracking.tools.vtracking_partner import root_partner_name

_logger = logging.getLogger(__name__)

# Nominatim giới hạn 1 request/giây; Google tính tiền theo lượt. Cron chạy lô nhỏ để
# không bị chặn IP và không đốt quota trong một lần.
GEOCODE_BATCH_SIZE = 20


class HlvVtrackingPlace(models.Model):
    """Địa điểm cố định hiện trên bản đồ: kho, đối tác, bãi đỗ...

    Khác với xe — xe tự di chuyển và toạ độ do thiết bị báo; địa điểm đứng yên và toạ độ
    do người khai hoặc máy tra rồi người duyệt.

    Toạ độ nằm ở ĐÂY chứ không nằm ở ``res.partner``: nhiều mã khách trong Odoo thường
    trỏ về cùng một địa chỉ vật lý, nên gắn toạ độ vào từng mã khách sẽ sinh ra nhiều
    ghim chồng nhau tại một chỗ. ``partner_id`` chỉ là đường dẫn ngược về đối tác.
    """

    _name = 'hlv.vtracking.place'
    _description = 'Địa điểm trên bản đồ'
    _inherit = ['mail.thread']
    _order = 'type_id, name'

    name = fields.Char(required=True, index=True, tracking=True)
    type_id = fields.Many2one(
        'hlv.vtracking.place.type', string='Loại', required=True, index=True, tracking=True,
        ondelete='restrict',
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Công ty', required=True, index=True,
        default=lambda self: self.env.company,
    )

    partner_id = fields.Many2one(
        'res.partner', string='Đối tác', index=True, tracking=True,
        help='Để trống nếu địa điểm không ứng với đối tác nào, ví dụ bãi đỗ xe.',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho trong Odoo', index=True, tracking=True,
        help='Chỉ điền cho địa điểm loại Kho. Nhờ đó khi kế hoạch xuất phát từ kho này, '
             'màn chọn phiếu biết ưu tiên phiếu xuất của đúng kho đó.',
    )
    address = fields.Char(
        string='Địa chỉ để tra toạ độ', tracking=True,
        help='Để trống thì lấy địa chỉ của đối tác. Điền tay khi địa chỉ trong Odoo quá '
             'sơ sài để máy tra được.',
    )
    address_used = fields.Char(
        string='Địa chỉ dùng khi tra', compute='_compute_address_used',
        help='Chuỗi thật sự gửi đi tra toạ độ. Xem để biết vì sao máy tra trượt.',
    )
    phone = fields.Char(related='partner_id.phone', readonly=True)
    note = fields.Text()

    # --- Toạ độ -------------------------------------------------------------
    latitude = fields.Float(string='Vĩ độ', digits=(10, 7), tracking=True)
    longitude = fields.Float(string='Kinh độ', digits=(10, 7), tracking=True)
    has_coords = fields.Boolean(compute='_compute_has_coords', store=True, string='Có toạ độ')
    geo_state = fields.Selection(
        [
            ('none', 'Chưa tra'),
            ('pending_review', 'Máy tra — chờ duyệt'),
            ('confirmed', 'Đã duyệt'),
            ('manual', 'Nhập tay'),
            ('failed', 'Máy không tìm được'),
        ],
        string='Tình trạng toạ độ', default='none', required=True, index=True, tracking=True,
    )
    geo_source = fields.Selection(
        [('geocode', 'Máy tra'), ('manual', 'Nhập tay'), ('partner', 'Lấy từ đối tác')],
        string='Nguồn toạ độ', readonly=True,
    )
    geo_raw_result = fields.Text(string='Kết quả máy trả về', readonly=True)
    geo_checked_by_id = fields.Many2one('res.users', string='Người duyệt', readonly=True)
    geo_checked_at = fields.Datetime(string='Duyệt lúc', readonly=True)
    geo_input = fields.Char(
        string='Dán toạ độ',
        help='Dán thẳng dạng "10.78950, 106.99179" từ Google Maps rồi bấm Lưu toạ độ.',
    )
    map_url = fields.Char(compute='_compute_map_url', string='Mở Google Maps')

    _sql_constraints = [
        ('name_type_company_uniq', 'unique(name, type_id, company_id)',
         'Đã có địa điểm cùng tên trong cùng loại.'),
    ]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('latitude', 'longitude')
    def _compute_has_coords(self):
        for place in self:
            place.has_coords = bool(place.latitude) and bool(place.longitude)

    @api.depends('address', 'partner_id')
    def _compute_address_used(self):
        for place in self:
            place.address_used = place._address_for_geocode()

    @api.depends('latitude', 'longitude')
    def _compute_map_url(self):
        for place in self:
            place.map_url = (
                'https://www.google.com/maps?q=%s,%s' % (place.latitude, place.longitude)
                if place.latitude and place.longitude else False
            )

    def _address_for_geocode(self):
        """Chuỗi địa chỉ gửi đi tra toạ độ.

        Ưu tiên ô ``address`` điền tay, sau đó mới ghép từ đối tác. Ghép kèm TÊN địa điểm
        vào đầu chuỗi: Google tra được cả tên doanh nghiệp, nên "Công ty X, đường Y" ra
        kết quả đúng hơn hẳn chỉ mỗi "đường Y" khi địa chỉ Odoo chỉ có cấp phường.

        Trả về chuỗi rỗng khi không có gì để tra.
        """
        self.ensure_one()
        if self.address:
            return self.address.strip()
        partner = self.partner_id
        if not partner:
            return (self.name or '').strip()
        parts = [
            self.name or partner.name,
            partner.street, partner.street2, partner.city,
            partner.state_id.name, partner.country_id.name,
        ]
        return ', '.join(part.strip() for part in parts if part and part.strip())

    # ------------------------------------------------------------------
    # Geocode: máy tra trước, người duyệt sau
    # ------------------------------------------------------------------
    def _geocode_one(self):
        """Gọi ``base.geocoder`` cho một địa điểm. Không tự viết HTTP client.

        Nhà cung cấp (OpenStreetMap hay Google) do ``base_geolocalize`` quyết định qua
        tham số hệ thống — xem ô "Nhà cung cấp tra toạ độ" ở cấu hình V-Tracking.
        """
        self.ensure_one()
        address = self._address_for_geocode()
        if not address:
            self.write({'geo_state': 'failed', 'geo_raw_result': 'Không có địa chỉ để tra.'})
            return False
        try:
            result = self.env['base.geocoder'].sudo().geo_find(address)
        except Exception as exc:  # noqa: BLE001 — provider lỗi không được làm gãy cả lô
            _logger.warning('Tra toạ độ lỗi cho "%s": %s', self.display_name, exc)
            self.write({'geo_state': 'failed', 'geo_raw_result': 'Lỗi khi tra: %s' % exc})
            return False
        if not result:
            self.write({
                'geo_state': 'failed',
                'geo_raw_result': 'Không tìm thấy toạ độ cho: %s' % address,
            })
            return False
        self.write({
            'latitude': result[0],
            'longitude': result[1],
            'geo_source': 'geocode',
            'geo_state': 'pending_review',
            'geo_raw_result': json.dumps(
                {'address': address, 'lat': result[0], 'lng': result[1]}, ensure_ascii=False,
            ),
        })
        return True

    def action_geocode_now(self):
        """Tra lại toạ độ rồi báo kết quả."""
        return self._geocode_notification(self._geocode_now_silently(), len(self))

    def _geocode_now_silently(self):
        """Tra toạ độ cho cả recordset, trả về SỐ địa điểm tra được.

        Bỏ qua địa điểm đã nhập tay: toạ độ người dán là nguồn đáng tin nhất, máy không
        được đè lên.

        Không trả thông báo để dùng được cả khi tra chỉ là bước phụ của việc khác (tạo
        địa điểm hàng loạt) — việc đó đã có màn hình kết quả riêng.
        """
        return sum(
            1 for place in self
            if place.geo_state != 'manual' and place._geocode_one()
        )

    def _geocode_notification(self, done, total):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tra toạ độ',
                'message': 'Tra được %s/%s địa điểm. Kết quả máy tra cần duyệt trước khi '
                           'dùng — mở bộ lọc "Chờ duyệt" để soát.' % (done, total),
                'type': 'success' if done else 'warning',
                'sticky': False,
            },
        }

    def action_confirm_geo(self):
        """Duyệt toạ độ máy đoán."""
        for place in self:
            if not place.has_coords:
                raise UserError('Địa điểm "%s" chưa có toạ độ để duyệt.' % place.name)
            place.write({
                'geo_state': 'confirmed',
                'geo_checked_by_id': self.env.user.id,
                'geo_checked_at': fields.Datetime.now(),
            })
        return True

    def action_save_manual_geo(self):
        """Lưu toạ độ dán tay từ ô ``geo_input``."""
        for place in self:
            parsed = parse_latlng(place.geo_input)
            if not parsed:
                raise UserError(
                    'Không đọc được toạ độ "%s". Dán đúng dạng: 10.78950, 106.99179'
                    % (place.geo_input or '')
                )
            place.write({
                'latitude': parsed[0],
                'longitude': parsed[1],
                'geo_source': 'manual',
                'geo_state': 'manual',
                'geo_input': False,
                'geo_checked_by_id': self.env.user.id,
                'geo_checked_at': fields.Datetime.now(),
            })
        return True

    def action_open_gmaps(self):
        self.ensure_one()
        if not self.map_url:
            raise UserError('Địa điểm này chưa có toạ độ.')
        return {'type': 'ir.actions.act_url', 'url': self.map_url, 'target': 'new'}

    @api.model
    def _cron_geocode_pending(self, limit=GEOCODE_BATCH_SIZE):
        """Tra toạ độ cho địa điểm chưa tra. KHÔNG đụng địa điểm đã duyệt/nhập tay."""
        places = self.search([('geo_state', '=', 'none'), ('active', '=', True)], limit=limit)
        done = sum(1 for place in places if place._geocode_one())
        if places:
            _logger.info('Tra toạ độ địa điểm: xử lý %s, thành công %s', len(places), done)
        return done

    # ------------------------------------------------------------------
    # Dữ liệu cho bản đồ
    # ------------------------------------------------------------------
    def _map_payload(self):
        """Một địa điểm ở dạng dict để vẽ ghim.

        Chỉ trả địa điểm ĐÃ có toạ độ — khác với xe (xe chưa có toạ độ vẫn trả về để
        danh sách hiện đủ đội). Địa điểm chưa tra được là việc cần xử lý ở màn quản lý
        địa điểm, không phải thứ để nhìn trên bản đồ.
        """
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'type_id': self.type_id.id,
            'type_name': self.type_id.name,
            'color': self.type_id.color,
            'size': self.type_id.size,
            'show_label': self.type_id.show_label,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'partner_name': root_partner_name(self.partner_id),
            'phone': self.phone or '',
            'address': self.address_used or '',
            'geo_state': self.geo_state,
        }
