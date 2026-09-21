import logging

from odoo import api, fields, models

from ..tools.vtracking_address import address_key, normalize_address

_logger = logging.getLogger(__name__)

# Khung toạ độ Việt Nam (rộng rãi, có kể cả đảo). Kết quả rơi ra ngoài khung này gần như
# luôn là geocoder khớp nhầm sang một nước khác — địa chỉ tiếng Việt viết tắt rất dễ bị
# hiểu thành tên đường ở nước ngoài. Một điểm sai kiểu đó làm quãng đường cả kế hoạch nhảy
# lên hàng nghìn km mà không ai biết vì sao, nên phải chặn ngay chỗ này.
VN_LAT_MIN, VN_LAT_MAX = 8.0, 23.6
VN_LNG_MIN, VN_LNG_MAX = 102.0, 110.0


def is_inside_vietnam(latitude, longitude):
    """Toạ độ có nằm trong khung Việt Nam không. Hàm thuần, dùng để lọc kết quả geocode."""
    if latitude is None or longitude is None:
        return False
    return (
        VN_LAT_MIN <= latitude <= VN_LAT_MAX
        and VN_LNG_MIN <= longitude <= VN_LNG_MAX
    )


class HlvVtrackingAddress(models.Model):
    """Kho toạ độ đã tra, tra theo địa chỉ chữ.

    Lý do tồn tại: địa chỉ giao trên phiếu là ô chữ tự do, và cùng một khách thì tháng
    nào cũng lặp lại đúng địa chỉ đó. Gọi Google mỗi lần xếp kế hoạch là trả tiền nhiều
    lần cho một câu trả lời không đổi.

    Luật bất di bất dịch: **tra ở đây trước, không thấy mới gọi ra ngoài.** Mọi đường vào
    đều phải đi qua ``resolve()``; đừng gọi ``base.geocoder`` thẳng từ chỗ khác.
    """

    _name = 'hlv.vtracking.address'
    _description = 'Toạ độ đã tra theo địa chỉ'
    _order = 'hit_count desc, id desc'
    _rec_name = 'raw_address'

    raw_address = fields.Char(
        string='Địa chỉ gốc', required=True, readonly=True,
        help='Nguyên văn lần đầu gặp. Giữ lại để soát khi toạ độ sai.',
    )
    normalized_address = fields.Char(
        string='Địa chỉ đã chuẩn hoá', readonly=True,
        help='Chuỗi thật sự gửi đi tra: bỏ dấu, mở viết tắt (P.5 → phuong 5).',
    )
    address_key = fields.Char(
        string='Khoá so khớp', required=True, readonly=True, index=True,
        help='Chỉ chữ và số. Cùng một địa chỉ viết khác nhau vẫn ra cùng khoá này.',
    )

    latitude = fields.Float(string='Vĩ độ', digits=(10, 7))
    longitude = fields.Float(string='Kinh độ', digits=(10, 7))
    has_coords = fields.Boolean(compute='_compute_has_coords', store=True)
    outside_vietnam = fields.Boolean(
        compute='_compute_has_coords', store=True, string='Ngoài Việt Nam',
        help='Toạ độ nằm ngoài khung Việt Nam — gần như luôn là geocoder khớp nhầm. Một '
             'điểm như vậy đủ để quãng đường cả kế hoạch nhảy lên hàng nghìn km.',
    )
    geo_state = fields.Selection(
        [
            ('pending_review', 'Máy tra — chờ duyệt'),
            ('confirmed', 'Đã duyệt'),
            ('manual', 'Nhập tay'),
            ('failed', 'Máy không tìm được'),
        ],
        string='Tình trạng', default='pending_review', required=True, index=True,
    )
    geo_source = fields.Selection(
        [('geocode', 'Máy tra'), ('manual', 'Nhập tay'), ('place', 'Từ địa điểm')],
        string='Nguồn', readonly=True,
    )
    geo_raw_result = fields.Text(string='Kết quả máy trả về', readonly=True)
    geo_input = fields.Char(
        string='Dán toạ độ',
        help='Dán "10.78950, 106.99179" từ Google Maps rồi bấm Lưu toạ độ.',
    )

    hit_count = fields.Integer(
        string='Số lần dùng lại', default=0, readonly=True,
        help='Mỗi lượt là một lần KHÔNG phải gọi ra ngoài. Cột này cho thấy cache tiết '
             'kiệm được bao nhiêu.',
    )
    last_used_at = fields.Datetime(string='Dùng lần cuối', readonly=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True, default=lambda self: self.env.company,
    )

    _sql_constraints = [
        # Khoá là thứ chống gọi trùng. Không có ràng buộc này thì hai lượt xếp kế hoạch
        # chạy song song sẽ tạo hai bản ghi cho cùng một địa chỉ và cache mất tác dụng.
        ('key_company_uniq', 'unique(address_key, company_id)',
         'Địa chỉ này đã có trong kho toạ độ.'),
    ]

    @api.depends('latitude', 'longitude')
    def _compute_has_coords(self):
        for record in self:
            record.has_coords = bool(record.latitude) and bool(record.longitude)
            record.outside_vietnam = record.has_coords and not is_inside_vietnam(
                record.latitude, record.longitude,
            )

    # ------------------------------------------------------------------
    # Đường vào duy nhất
    # ------------------------------------------------------------------
    @api.model
    def resolve(self, raw_address, allow_remote=True):
        """Địa chỉ chữ -> bản ghi toạ độ. Chỉ gọi ra ngoài khi trong kho chưa có.

        ``allow_remote=False`` thì chỉ tra trong kho, không bao giờ gọi mạng — dùng khi
        xếp hàng loạt và muốn xem trước có bao nhiêu địa chỉ phải tra.

        Trả về recordset rỗng nếu địa chỉ rỗng hoặc không rút được khoá.

        Bản ghi ``failed`` vẫn được trả về chứ không tra lại: máy đã trượt một lần thì
        lần sau cũng trượt với đúng chuỗi đó, tra lại chỉ tốn thêm tiền. Muốn thử lại thì
        bấm nút trên bản ghi đó.
        """
        key = address_key(raw_address)
        if not key:
            return self.browse()

        existing = self.search([
            ('address_key', '=', key),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if existing:
            # Cách viết đã được gộp vào địa chỉ khác -> dùng bản gốc (xem vtracking_address_merge).
            existing = existing._canonical()
            existing._mark_hit()
            return existing
        if not allow_remote:
            return self.browse()

        record = self.create({
            'raw_address': raw_address,
            'normalized_address': self._normalized_for_provider(raw_address),
            'address_key': key,
        })
        record._geocode()
        return record

    @api.model
    def seed(self, raw_address, latitude, longitude, source='place'):
        """Mồi sẵn một cặp địa chỉ → toạ độ ĐÃ BIẾT vào kho, không gọi geocoder.

        Dùng khi đã có toạ độ đáng tin từ nguồn khác — điểm giao người ghim trên bản đồ
        chẳng hạn. Mồi trước thì lần đầu gặp địa chỉ đó trên phiếu đã tra trúng ngay: vừa
        không tốn lượt gọi, vừa dùng đúng toạ độ người ghim thay vì phỏng đoán của máy.

        Trả về bản ghi, hoặc recordset rỗng nếu địa chỉ không rút được khoá.

        **Không đè lên bản ghi người đã sửa tay** (``manual``) hay đã duyệt (``confirmed``):
        mồi là để lấp chỗ trống, không phải để ghi đè công sức của người khác.
        """
        key = address_key(raw_address)
        if not key or not latitude or not longitude:
            return self.browse()
        existing = self.search([
            ('address_key', '=', key), ('company_id', '=', self.env.company.id),
        ], limit=1)
        if existing:
            existing = existing._canonical()
        values = {
            'latitude': latitude,
            'longitude': longitude,
            'geo_source': source,
            # Toạ độ đã biết chắc thì không cần ai duyệt lại, và máy không được đè lên.
            'geo_state': 'manual',
            'geo_raw_result': False,
        }
        if existing:
            if existing.geo_state in ('manual', 'confirmed'):
                return existing
            existing.write(values)
            return existing
        return self.create(dict(
            values,
            raw_address=raw_address,
            normalized_address=self._normalized_for_provider(raw_address),
            address_key=key,
        ))

    @api.model
    def _normalized_for_provider(self, raw_address):
        """Chuỗi gửi đi tra, cắt theo đúng thứ nhà cung cấp hiện tại dùng được.

        Google tra được cả tên doanh nghiệp nên giữ lại cụm tên; Nominatim thì không —
        gửi tên công ty vào chỉ làm nó đi tìm một doanh nghiệp cùng tên ở nơi khác.
        """
        # Tham số lưu ID nhà cung cấp chứ không lưu tên — đọc qua helper, đừng so chuỗi.
        provider = self.env['res.company']._geocode_provider_tech_name()
        return normalize_address(raw_address, drop_company=provider != 'googlemap')

    def _mark_hit(self):
        """Ghi nhận một lần dùng lại. Không để lỗi thống kê làm hỏng việc chính."""
        self.ensure_one()
        try:
            self.sudo().write({
                'hit_count': (self.hit_count or 0) + 1,
                'last_used_at': fields.Datetime.now(),
            })
        except Exception:  # noqa: BLE001
            _logger.warning('Không ghi được số lần dùng lại của địa chỉ %s.', self.id)
        return self

