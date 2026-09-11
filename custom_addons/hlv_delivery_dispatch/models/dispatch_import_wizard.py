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
        if layer_name in cache:
            return cache[layer_name]
        Zone = self.env['hlv.delivery.zone']
        zone = Zone.search([
            ('warehouse_id', '=', self.warehouse_id.id), ('name', '=ilike', layer_name),
        ], limit=1)
        if not zone and self.create_missing_zone:
            zone = Zone.create({'name': layer_name, 'warehouse_id': self.warehouse_id.id})
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
        if cust_rows is not None:
            lines += self._link_partners(cust_rows)
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

    def _link_partners(self, rows):
        """Ghép khách Odoo với điểm giao theo tên đã chuẩn hoá.

        Chỉ ghép khách chưa có điểm — không cướp lại khách đã gán tay.
        """
        Point = self.env['hlv.delivery.point']
        Partner = self.env['res.partner']
        if isinstance(rows, dict):
            rows = rows.get('customers') or rows.get('items') or []
        names = []
        for row in rows:
            if isinstance(row, str):
                names.append(row)
            elif isinstance(row, dict):
                names.append(row.get('name') or row.get('n') or row.get('partner_name') or '')
        points_by_key = {p.map_name_key: p for p in Point.search([]) if p.map_name_key}
        linked = unmatched = 0
        unmatched_names = []
        for name in names:
            name = (name or '').strip()
            if not name:
                continue
            key = normalize_name(name)
            point = points_by_key.get(key)
            if not point:
                unmatched += 1
                if len(unmatched_names) < 30:
                    unmatched_names.append(name)
                continue
            partners = Partner.search([
                ('name', '=ilike', name), ('x_delivery_point_id', '=', False),
            ])
            if partners:
                partners.write({'x_delivery_point_id': point.id})
                linked += len(partners)
        out = [
            '— Ghép khách với điểm giao —',
            'Đã gắn điểm cho %s mã khách' % linked,
            'Không khớp được %s tên' % unmatched,
        ]
        if unmatched_names:
            out.append('Cần xử lý tay: ' + ', '.join(unmatched_names))
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
