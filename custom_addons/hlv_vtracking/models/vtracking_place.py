import logging

from odoo import api, fields, models
from odoo.addons.hlv_vtracking.tools.vtracking_partner import root_partner_name

_logger = logging.getLogger(__name__)


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
    zone_id = fields.Many2one(
        'hlv.vtracking.zone', string='Cụm tuyến', index=True, tracking=True,
        help='Quyết định định mức thời gian dùng khi tính kế hoạch đi qua điểm này.',
    )
    partner_ref = fields.Char(related='partner_id.ref', string='Mã khách', readonly=True)
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
        [('geocode', 'Máy tra'), ('manual', 'Nhập tay'), ('partner', 'Lấy từ đối tác'),
         ('map', 'Bản đồ router')],
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
            'zone_id': self.zone_id.id or None,
            'zone_name': self.zone_id.name or '',
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
