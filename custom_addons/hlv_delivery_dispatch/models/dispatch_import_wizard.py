import base64
import json
import logging

from odoo import fields, models
from odoo.exceptions import UserError

from .dispatch_utils import normalize_name, parse_latlng

_logger = logging.getLogger(__name__)

# Hai lớp này trên Google My Maps KHÔNG phải cụm tuyến: một lớp là đường chỉ dẫn,
# một lớp là ghi chú quy tắc. Nhận diện bằng từ khoá vì tên lớp do người vẽ đặt tay.
NON_ZONE_LAYER_HINTS = ('chỉ đường', 'chi duong', 'chuyển phát nhanh nếu', 'chuyen phat nhanh neu')


class HlvDispatchImportWizard(models.TransientModel):
    """Nhập điểm giao từ bản trích Google My Maps và ghép với khách trong Odoo.

    Chạy lại được nhiều lần: khớp theo tên đã chuẩn hoá (map_name_key) chứ không theo
    thứ tự, vì My Maps không xuất ID ổn định. Lần nhập sau chỉ cập nhật toạ độ và
    KHÔNG đè lên toạ độ người đã nhập tay.
    """

    _name = 'hlv.dispatch.import.wizard'
    _description = 'Nhập dữ liệu điều phối'

    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho', required=True,
        default=lambda self: self.env['stock.warehouse'].search(
            [('x_dispatch_enabled', '=', True)], limit=1,
        ),
    )
    map_file = fields.Binary(string='File điểm bản đồ (map2.json)')
    map_filename = fields.Char()
    cust_file = fields.Binary(string='File khách hàng (cust.json)')
    cust_filename = fields.Char()
    create_missing_zone = fields.Boolean(
        string='Tự tạo cụm còn thiếu', default=True,
        help='Tạo cụm theo tên lớp bản đồ nếu chưa có. Hai lớp không phải cụm (lớp chỉ '
             'đường, lớp ghi quy tắc) luôn bị bỏ qua.',
    )
    result_log = fields.Text(string='Kết quả', readonly=True)

    # ------------------------------------------------------------------
    def _load_json(self, data, filename):
        if not data:
            return None
        try:
            return json.loads(base64.b64decode(data).decode('utf-8'))
        except Exception as exc:
            raise UserError('Không đọc được file %s: %s' % (filename or '', exc))

    def _is_zone_layer(self, layer_name):
        lowered = (layer_name or '').lower()
        return not any(hint in lowered for hint in NON_ZONE_LAYER_HINTS)

    def _get_zone(self, layer_name, cache):
        """Khớp một lớp bản đồ với cụm tuyến.

        Tên lớp trên My Maps không trùng tên cụm ("Tuyến Nhơn Trạch" vs "Nhơn Trạch",
        "ROUTER TUYẾN BÌNH SƠN LONG THÀNH" vs "Lộc An – Bình Sơn"), nên so tên chính xác
        sẽ sinh ra cụm trùng và đẩy hết điểm sang cụm rỗng định mức mặc định.

        Thứ tự khớp: tên lớp đã khai trên cụm -> tên cụm đã chuẩn hoá -> tạo mới.
        """
        if layer_name in cache:
            return cache[layer_name]
        Zone = self.env['hlv.delivery.zone']
        layer_key = normalize_name(layer_name)
        zones = Zone.search([('warehouse_id', '=', self.warehouse_id.id)])

        zone = Zone.browse()
        for candidate in zones:
            keys = [normalize_name(k) for k in (candidate.map_layer_keys or '').split(',')]
            if layer_key and layer_key in [k for k in keys if k]:
                zone = candidate
                break
        if not zone:
            for candidate in zones:
                if layer_key and normalize_name(candidate.name) == layer_key:
                    zone = candidate
                    break
        if not zone and self.create_missing_zone:
            # Ghi lại tên lớp ngay lúc tạo: sau này đổi tên cụm cho gọn thì lần import
            # tiếp theo vẫn khớp được, không sinh cụm trùng.
            zone = Zone.create({
                'name': layer_name,
                'warehouse_id': self.warehouse_id.id,
                'map_layer_keys': layer_name,
            })
        cache[layer_name] = zone
        return zone

    # ------------------------------------------------------------------
    def action_import(self):
        self.ensure_one()
        lines = []
        map_rows = self._load_json(self.map_file, self.map_filename)
        cust_rows = self._load_json(self.cust_file, self.cust_filename)
        if not map_rows and not cust_rows:
            raise UserError('Chưa chọn file nào để nhập.')
        if map_rows is not None:
            lines += self._import_points(map_rows)
        # Ghép khách chạy cả khi không có file đối chiếu: việc ghép dựa trên quét
        # res.partner, file chỉ dùng để báo cáo khách nào còn thiếu điểm.
        lines += self._link_partners(cust_rows or [])
        lines += self._quality_report()
        self.result_log = '\n'.join(lines)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _import_points(self, rows):
        Point = self.env['hlv.delivery.point']
        if not isinstance(rows, list):
            raise UserError('File bản đồ phải là một danh sách điểm (JSON array).')
        zone_cache = {}
        created = updated = skipped_layer = coord_set = 0
        now = fields.Datetime.now()
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = (row.get('n') or '').strip()
            if not name:
                continue
            layer = (row.get('f') or '').strip()
            if not self._is_zone_layer(layer):
                skipped_layer += 1
                continue
            key = normalize_name(name)
            if not key:
                continue
            point = Point.search([('map_name_key', '=', key)], limit=1)
            vals = {
                'name': name,
                'address': (row.get('ad') or '').strip(),
                'map_layer': layer,
                'map_synced': True,
                'map_last_synced_at': now,
            }
            zone = self._get_zone(layer, zone_cache) if layer else None
            if zone:
                vals['zone_id'] = zone.id
            coords = parse_latlng(row.get('c'))
            note = (row.get('gh') or '').strip()
            if point:
                # Không đè toạ độ người đã nhập tay — đó là nguồn đáng tin nhất.
                if coords and point.geo_state != 'manual':
                    vals.update({
                        'latitude': coords[0], 'longitude': coords[1],
                        'geo_source': 'map', 'geo_state': 'confirmed',
                    })
                    coord_set += 1
                if point.zone_id and 'zone_id' in vals:
                    # Cụm đã gán tay thì giữ nguyên, lớp bản đồ chỉ là gợi ý.
                    vals.pop('zone_id')
                point.write(vals)
                updated += 1
            else:
                if coords:
                    vals.update({
                        'latitude': coords[0], 'longitude': coords[1],
                        'geo_source': 'map', 'geo_state': 'confirmed',
                    })
                    coord_set += 1
                point = Point.create(vals)
                created += 1
            if note:
                profile = point.get_or_create_profile()
                if not profile.free_note:
                    profile.free_note = note
        return [
            '— Nhập điểm từ bản đồ —',
            'Tạo mới: %s · Cập nhật: %s' % (created, updated),
            'Bỏ qua %s ghim thuộc lớp không phải cụm tuyến' % skipped_layer,
            'Có toạ độ từ bản đồ: %s' % coord_set,
            '',
        ]

    def _customer_names_from_rows(self, rows):
        """Lấy tên khách từ file đối chiếu.

        File hiện dùng có dạng [{"k": khoá đã chuẩn hoá, "pn": tên trong Odoo,
        "visits": n, "orders": n}]. Vẫn nhận các dạng cũ để chạy lại được với file khác.
        """
        if isinstance(rows, dict):
            rows = rows.get('customers') or rows.get('items') or []
        names = []
        for row in rows:
            if isinstance(row, str):
                names.append(row)
            elif isinstance(row, dict):
                names.append(
                    row.get('pn') or row.get('name') or row.get('n')
                    or row.get('partner_name') or row.get('k') or ''
                )
        return [n.strip() for n in names if (n or '').strip()]

    def _link_partners(self, rows):
        """Gắn điểm giao cho khách trong Odoo, khớp theo TÊN đã chuẩn hoá.

        Quét thẳng res.partner chứ không dò từng tên trong file: Odoo sinh nhiều mã cho
        cùng một khách với tên viết hơi khác nhau (351 mã = 176 khách thật), nên khớp
        theo tên chính xác sẽ bỏ sót phần lớn. File đối chiếu chỉ dùng để biết khách nào
        đáng lẽ phải có điểm mà vẫn không ghép được.

        Chỉ ghép khách chưa có điểm — không cướp lại khách đã gán tay.
        """
        Point = self.env['hlv.delivery.point']
        Partner = self.env['res.partner']

        points_by_key = {}
        for point in Point.search([]):
            if point.map_name_key:
                points_by_key.setdefault(point.map_name_key, point)

        candidates = Partner.search([
            ('x_delivery_point_id', '=', False),
            ('customer_rank', '>', 0),
        ])
        linked = 0
        matched_keys = set()
        for partner in candidates:
            key = normalize_name(partner.name)
            point = points_by_key.get(key)
            if not point:
                continue
            partner.x_delivery_point_id = point.id
            matched_keys.add(key)
            linked += 1

        out = [
            '— Ghép khách với điểm giao —',
            'Quét %s mã khách chưa có điểm, gắn được %s mã' % (len(candidates), linked),
            'Số điểm đã có ít nhất một mã khách: %s' % len(matched_keys),
        ]

        # Đối chiếu với danh sách khách thật để biết còn thiếu ai.
        names = self._customer_names_from_rows(rows)
        if names:
            missing = []
            for name in names:
                key = normalize_name(name)
                if key in points_by_key:
                    continue
                if len(missing) < 30:
                    missing.append(name)
            out.append('Khách trong file chưa có điểm trên bản đồ: %s' % len(missing))
            if missing:
                out.append('Cần ghim thêm hoặc đặt lại tên: ' + ', '.join(missing))
        out.append('')
        return out

    def _quality_report(self):
        Point = self.env['hlv.delivery.point']
        total = Point.search_count([])
        no_coords = Point.search_count([('has_coords', '=', False)])
        no_zone = Point.search_count([('zone_id', '=', False)])
        no_profile = Point.search_count([('has_profile', '=', False)])
        return [
            '— Chất lượng dữ liệu —',
            '%s điểm · %s thiếu toạ độ · %s chưa gán cụm · %s chưa có thói quen'
            % (total, no_coords, no_zone, no_profile),
            'Đây là backlog cần xử lý: chạy cron tra toạ độ rồi duyệt, '
            'gán cụm tay, và giao sale điền thói quen khách.',
        ]
