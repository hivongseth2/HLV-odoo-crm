import base64
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.hlv_geo_utils.tools.geo_text import normalize_name, strip_accents

from ..tools.vtracking_map_import import (
    MapImportError, match_layer, parse_map_points, summarize,
)

_logger = logging.getLogger(__name__)

# Trần số ghim một lần. Bản đồ router hiện có 86 ghim; trần rộng gấp mười để không chặn
# lần mở rộng, nhưng vẫn đủ để một file sai định dạng không kéo về vài chục nghìn dòng.
MAX_POINTS = 1000


class HlvVtrackingPlaceImport(models.TransientModel):
    """Nhập điểm giao từ file ghim Google My Maps.

    Vì sao cần: điểm giao là mắt xích để một đơn hàng biết mình thuộc cụm tuyến nào. Khai
    tay 86 điểm thì không ai làm, mà không có chúng thì mọi thứ phía sau chạy trên dữ liệu
    rỗng — kế hoạch không biết cụm, không tính được định mức, không gợi ý được gì.

    Bản đồ router đã chia sẵn cụm bằng LỚP, và cách chia đó đúng: các điểm trong cùng lớp
    cách nhau 1–5 km. Wizard này chỉ việc đọc lại kết quả đó.
    """

    _name = 'hlv.vtracking.place.import'
    _description = 'Nhập điểm giao từ bản đồ'

    file_data = fields.Binary(string='File bản đồ (.json)', required=True, attachment=False)
    file_name = fields.Char(string='Tên file')
    type_id = fields.Many2one(
        'hlv.vtracking.place.type', string='Loại địa điểm', required=True,
        default=lambda self: self.env.ref('hlv_vtracking.place_type_partner', False),
        help='Áp cho mọi điểm tạo mới. Sửa lại từng điểm sau khi nhập cũng được.',
    )
    match_partner = fields.Boolean(
        string='Ghép với đối tác trong Odoo', default=True,
        help='Ghép theo TÊN đã chuẩn hoá (bỏ dấu, bỏ tiền tố pháp nhân). Ghép được thì đơn '
             'hàng của khách đó tự biết thuộc cụm nào — không ghép được thì phải gán tay.',
    )
    line_ids = fields.One2many('hlv.vtracking.place.import.line', 'wizard_id', string='Ghim')
    summary = fields.Text(string='Tóm tắt', readonly=True)

    to_create_count = fields.Integer(compute='_compute_counts', string='Sẽ tạo')
    existing_count = fields.Integer(compute='_compute_counts', string='Đã có')
    no_zone_count = fields.Integer(compute='_compute_counts', string='Chưa gán cụm')
    no_partner_count = fields.Integer(compute='_compute_counts', string='Chưa ghép đối tác')

    @api.depends('line_ids.to_create', 'line_ids.zone_id', 'line_ids.partner_id',
                 'line_ids.existing_place_id')
    def _compute_counts(self):
        for wizard in self:
            lines = wizard.line_ids
            wizard.existing_count = len(lines.filtered('existing_place_id'))
            selected = lines.filtered(lambda line: line.to_create and not line.existing_place_id)
            wizard.to_create_count = len(selected)
            wizard.no_zone_count = len(selected.filtered(lambda line: not line.zone_id))
            wizard.no_partner_count = len(selected.filtered(lambda line: not line.partner_id))

    # ------------------------------------------------------------------
    # Đọc file
    # ------------------------------------------------------------------
    def action_load(self):
        """Đọc file và dựng danh sách xem trước. Không tạo gì cả."""
        self.ensure_one()
        if not self.file_data:
            raise UserError('Chưa chọn file.')
        try:
            raw = base64.b64decode(self.file_data).decode('utf-8')
        except (ValueError, UnicodeDecodeError) as exc:
            raise UserError('Không đọc được file — phải là JSON mã hoá UTF-8. (%s)' % exc) from exc
        try:
            points = parse_map_points(raw)
        except MapImportError as exc:
            raise UserError(str(exc)) from exc
        if not points:
            raise UserError('File không có ghim nào dùng được (ghim phải có tên).')
        if len(points) > MAX_POINTS:
            raise UserError('File có %s ghim, tối đa %s một lần.' % (len(points), MAX_POINTS))

        self.line_ids.unlink()
        zones = self._zone_by_layer(points)
        partners = self._partner_by_key(points) if self.match_partner else {}
        existing = self._existing_by_key()

        self.line_ids = [
            fields.Command.create(self._line_values(point, zones, partners, existing))
            for point in points
        ]
        self.summary = self._format_summary(summarize(points))
        return self._reopen()

    def _line_values(self, point, zones, partners, existing):
        key = normalize_name(point['name'])
        place = existing.get(key)
        return {
            'layer': point['layer'],
            'name': point['name'],
            'address': point['address'],
            'note': ' · '.join(n for n in (point['route_note'], point['goods_note']) if n),
            'latitude': point['latitude'] or 0.0,
            'longitude': point['longitude'] or 0.0,
            'coords_error': point['coords_error'],
            'zone_id': zones.get(point['layer'], self.env['hlv.vtracking.zone']).id or False,
            'partner_id': partners.get(key, self.env['res.partner']).id or False,
            'existing_place_id': place.id if place else False,
            # Điểm đã có thì không tick sẵn: nhập lại đè lên toạ độ người đã sửa tay là
            # mất công sức của họ mà không ai biết.
            'to_create': not place,
        }

    # ------------------------------------------------------------------
    # Ghép
    # ------------------------------------------------------------------
    def _zone_by_layer(self, points):
        """dict {tên lớp: cụm tuyến} — ghép lớp bản đồ với cụm đã khai trong Odoo.

        Ghép theo TÊN đã chuẩn hoá, vì lớp trên bản đồ viết hoa và thêm chữ ("ROUTER TUYẾN
        BÌNH SƠN LONG THÀNH" ↔ cụm "Long Thành – Bình Sơn"). Lớp không khớp cụm nào thì để
        trống — người nhập tự chọn trên từng dòng. Bản đồ có lớp không phải cụm thật (một
        lớp chỉ đường, một lớp ghi quy tắc CPN), nên ép mọi lớp thành cụm là sai.
        """
        zones = self.env['hlv.vtracking.zone'].search([('company_id', '=', self.env.company.id)])
        by_name = {zone.name: zone for zone in zones}
        result = {}
        for layer in {point['layer'] for point in points if point['layer']}:
            matched = match_layer(layer, list(by_name), strip_accents)
            if matched:
                result[layer] = by_name[matched]
        return result

    def _partner_by_key(self, points):
        """dict {khoá tên: đối tác} cho các ghim — MỘT truy vấn.

        Ghép theo tên chuẩn hoá vì tên trên bản đồ khác tên trong Odoo ("Jungwoo vina" ↔
        "CÔNG TY TNHH JUNGWOO VINA"). Chỉ nhận PHÁP NHÂN GỐC: Odoo sinh nhiều mã cho cùng
        một công ty (351 mã = 176 khách thật), gắn điểm vào mã con thì đơn của mã khác sẽ
        không tìm thấy điểm.
        """
        keys = {normalize_name(point['name']) for point in points}
        keys.discard('')
        if not keys:
            return {}
        partners = self.env['res.partner'].search([
            ('is_company', '=', True), ('active', 'in', (True, False)),
        ])
        result = {}
        for partner in partners:
            key = normalize_name(partner.name)
            if key in keys and key not in result:
                result[key] = partner.commercial_partner_id or partner
        return result

    def _existing_by_key(self):
        """dict {khoá tên: điểm giao đã có} — để không tạo trùng khi nhập lại."""
        places = self.env['hlv.vtracking.place'].with_context(active_test=False).search([
            ('company_id', '=', self.env.company.id),
        ])
        result = {}
        for place in places:
            key = normalize_name(place.name)
            if key and key not in result:
                result[key] = place
        return result

    @api.model
    def _format_summary(self, stats):
        lines = [
            'Đọc được %s ghim: %s có toạ độ, %s chưa có, %s toạ độ lỗi.'
            % (stats['total'], stats['with_coords'], stats['without_coords'], stats['bad_coords']),
            'Các lớp trên bản đồ:',
        ]
        lines += ['  · %s — %s ghim' % (name or '(không có lớp)', count)
                  for name, count in stats['by_layer']]
        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Tạo
    # ------------------------------------------------------------------
    def action_create_places(self):
        """Tạo địa điểm cho các dòng đang tick."""
        self.ensure_one()
        lines = self.line_ids.filtered(lambda line: line.to_create and not line.existing_place_id)
        if not lines:
            raise UserError('Chưa chọn ghim nào để tạo.')
        places = self.env['hlv.vtracking.place'].create([
            line._place_values(self.type_id) for line in lines
        ])
        # Toạ độ từ bản đồ là người ghim nên đáng tin — mồi thẳng vào kho toạ độ để phiếu
        # có địa chỉ giống không phải gọi geocoder lần nào.
        seeded = places._seed_address_cache()
        _logger.info(
            'V-Tracking: nhập %s điểm giao từ bản đồ, mồi %s địa chỉ vào kho toạ độ.',
            len(places), seeded,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Điểm giao vừa nhập',
            'res_model': 'hlv.vtracking.place',
            'domain': [('id', 'in', places.ids)],
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_select_all(self):
        self.ensure_one()
        self.line_ids.filtered(lambda line: not line.existing_place_id).to_create = True
        return self._reopen()

    def action_select_with_zone(self):
        """Chỉ tick ghim đã ghép được cụm — bỏ qua lớp không phải cụm tuyến thật."""
        self.ensure_one()
        self.line_ids.to_create = False
        self.line_ids.filtered(
            lambda line: line.zone_id and not line.existing_place_id
        ).to_create = True
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
