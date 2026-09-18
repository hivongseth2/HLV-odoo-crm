from odoo import fields, models


class HlvVtrackingPlaceImportLine(models.TransientModel):
    """Một ghim trên bản đồ, kèm kết luận ghép cụm và ghép đối tác."""

    _name = 'hlv.vtracking.place.import.line'
    _description = 'Ghim bản đồ chờ nhập'
    _order = 'layer, name'

    wizard_id = fields.Many2one(
        'hlv.vtracking.place.import', required=True, ondelete='cascade', index=True,
    )
    layer = fields.Char(string='Lớp bản đồ', readonly=True)
    name = fields.Char(string='Tên ghim', readonly=True)
    address = fields.Char(string='Địa chỉ', readonly=True)
    note = fields.Char(string='Ghi chú trên bản đồ', readonly=True)

    latitude = fields.Float(string='Vĩ độ', digits=(10, 7), readonly=True)
    longitude = fields.Float(string='Kinh độ', digits=(10, 7), readonly=True)
    has_coords = fields.Boolean(compute='_compute_has_coords', string='Có toạ độ')
    coords_error = fields.Char(string='Lỗi toạ độ', readonly=True)

    zone_id = fields.Many2one('hlv.vtracking.zone', string='Cụm tuyến')
    partner_id = fields.Many2one(
        'res.partner', string='Đối tác trong Odoo',
        help='Chỉ chọn PHÁP NHÂN, không chọn liên hệ con. Ba mã khách của cùng một công ty '
             'phải trỏ về một điểm giao, nên gắn vào liên hệ con thì đơn của mã khác sẽ '
             'không tìm thấy điểm.',
    )
    partner_ref = fields.Char(
        related='partner_id.ref', string='Mã khách', readonly=True,
        help='Hiện ngay cạnh để soát: tên pháp nhân dài và nhiều công ty tên gần giống '
             'nhau, mã thì ngắn và duy nhất.',
    )
    existing_place_id = fields.Many2one(
        'hlv.vtracking.place', string='Điểm đã có', readonly=True,
    )
    to_create = fields.Boolean(string='Tạo')

    def _compute_has_coords(self):
        for line in self:
            line.has_coords = bool(line.latitude) and bool(line.longitude)

    def _place_values(self, place_type):
        """Giá trị tạo ``hlv.vtracking.place`` từ ghim này.

        Toạ độ từ bản đồ lưu ở trạng thái ``manual``: chúng do NGƯỜI ghim và đã dùng chạy
        tuyến thật nhiều tháng, đáng tin hơn hẳn kết quả máy tra. Trạng thái đó cũng khiến
        máy không bao giờ đè lên — cùng nguyên tắc với toạ độ dán tay.

        Ghim chưa có toạ độ để ``none`` để tác vụ nền tra dần.
        """
        self.ensure_one()
        values = {
            'name': self.name,
            'type_id': place_type.id,
            'zone_id': self.zone_id.id or False,
            'partner_id': self.partner_id.id or False,
            'address': self.address or False,
            'note': self.note or False,
        }
        if self.latitude and self.longitude:
            values.update({
                'latitude': self.latitude,
                'longitude': self.longitude,
                'geo_source': 'map',
                'geo_state': 'manual',
            })
        else:
            values['geo_state'] = 'none'
        return values
