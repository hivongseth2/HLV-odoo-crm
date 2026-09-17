import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.hlv_geo_utils.tools.geo_text import parse_latlng

from ..tools.vtracking_address import address_key, normalize_address

_logger = logging.getLogger(__name__)


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
        [('geocode', 'Máy tra'), ('manual', 'Nhập tay')],
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
            existing._mark_hit()
            return existing
        if not allow_remote:
            return self.browse()

        record = self.create({
            'raw_address': raw_address,
            'normalized_address': normalize_address(raw_address),
            'address_key': key,
        })
        record._geocode()
        return record

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

    # ------------------------------------------------------------------
    # Tra toạ độ
    # ------------------------------------------------------------------
    def _geocode(self):
        """Gọi ``base.geocoder`` cho các bản ghi chưa có toạ độ đã duyệt.

        Gửi đi bản ĐÃ CHUẨN HOÁ chứ không phải nguyên văn: bỏ dấu và mở viết tắt giúp
        provider khớp tốt hơn hẳn với địa chỉ gõ tắt kiểu "P.5, Q.GV".
        """
        done = 0
        for record in self:
            if record.geo_state == 'manual':
                # Toạ độ người dán tay là nguồn đáng tin nhất, máy không được đè lên.
                continue
            address = record.normalized_address or record.raw_address
            try:
                result = self.env['base.geocoder'].sudo().geo_find(address)
            except Exception as exc:  # noqa: BLE001 — provider lỗi không được làm gãy cả lô
                _logger.warning('Tra toạ độ lỗi cho "%s": %s', address, exc)
                record.write({'geo_state': 'failed', 'geo_raw_result': 'Lỗi khi tra: %s' % exc})
                continue
            if not result:
                record.write({
                    'geo_state': 'failed',
                    'geo_raw_result': 'Không tìm thấy toạ độ cho: %s' % address,
                })
                continue
            record.write({
                'latitude': result[0],
                'longitude': result[1],
                'geo_source': 'geocode',
                'geo_state': 'pending_review',
                'geo_raw_result': json.dumps(
                    {'address': address, 'lat': result[0], 'lng': result[1]}, ensure_ascii=False,
                ),
            })
            done += 1
        return done

    def action_geocode_retry(self):
        """Tra lại — dùng khi lần trước trượt hoặc khi đã đổi nhà cung cấp."""
        return self._geocode()

    def action_confirm(self):
        self.write({'geo_state': 'confirmed'})
        return True

    def action_save_manual_geo(self):
        for record in self:
            parsed = parse_latlng(record.geo_input)
            if not parsed:
                raise UserError(
                    'Không đọc được toạ độ "%s". Dán đúng dạng: 10.78950, 106.99179'
                    % (record.geo_input or '')
                )
            record.write({
                'latitude': parsed[0],
                'longitude': parsed[1],
                'geo_source': 'manual',
                'geo_state': 'manual',
                'geo_input': False,
            })
        return True

    def action_open_gmaps(self):
        self.ensure_one()
        if not self.has_coords:
            raise UserError('Bản ghi này chưa có toạ độ.')
        return {
            'type': 'ir.actions.act_url',
            'url': 'https://www.google.com/maps?q=%s,%s' % (self.latitude, self.longitude),
            'target': 'new',
        }
