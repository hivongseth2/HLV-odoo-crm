"""Gộp các địa điểm TRÙNG.

Bản bị gộp được LƯU TRỮ (active = False) chứ không xoá: địa điểm có chatter, có lịch sử
duyệt toạ độ — xoá là mất dấu vết, và gộp nhầm thì không khôi phục được. Lưu trữ thì mở
lại được từ bộ lọc "Đã lưu trữ".

Việc CHỌN gộp gì nằm ở ``tools/vtracking_dedup`` (chỉ đề xuất). Ở đây chỉ gộp đúng các id
được chỉ định.
"""

from odoo import models
from odoo.exceptions import UserError

from ..tools.vtracking_dedup import GEO_RANK

# Ô của địa điểm lấy từ bản gộp khi bản giữ còn TRỐNG. Không bao giờ đè ô đã có giá trị.
FILL_FIELDS = ('partner_id', 'zone_id', 'warehouse_id', 'address', 'note')
# Ô thói quen khách chuyển sang bản giữ khi bản giữ còn trống.
PROFILE_FIELDS = (
    'procedure_required', 'delivery_method', 'default_vehicle_id', 'extra_service_minutes',
    'receiving_from', 'receiving_to', 'payment_method', 'free_note',
)


def _write_value(record, field):
    """Giá trị của ``record[field]`` ở dạng dùng được cho ``write()`` (many2one -> id)."""
    value = record[field]
    return value.id if record._fields[field].type == 'many2one' else value


def _write_values(record, field_names):
    """Các ô CÓ giá trị của ``record`` ở dạng dùng được cho ``write()``."""
    return {field: _write_value(record, field) for field in field_names if record[field]}


def _blank_fill_values(keep, donors, field_names):
    """Ô đang trống ở ``keep`` -> giá trị lấy từ bản gộp đầu tiên có giá trị đó."""
    values = {}
    for field in field_names:
        if keep[field]:
            continue
        donor = donors.filtered(field)[:1]
        if donor:
            values[field] = _write_value(donor, field)
    return values


class HlvVtrackingPlaceMerge(models.Model):
    _inherit = 'hlv.vtracking.place'

    def merge_into(self, keep):
        """Gộp ``self`` vào ``keep``. Trả về dict tóm tắt.

        - Ô trống của bản giữ lấy từ bản gộp (đối tác, cụm, kho, địa chỉ, ghi chú).
        - Bản giữ chưa có toạ độ -> lấy toạ độ đáng tin nhất trong các bản gộp.
        - Thói quen khách: bản giữ chưa có thì chuyển nguyên bộ sang; đã có thì chỉ lấp ô
          trống rồi bỏ bộ thừa. Mất thói quen khách là mất công người điền.
        - Mọi thứ đang trỏ tới bản gộp (điểm xuất phát của kế hoạch và của xe, điểm giao
          của dòng kế hoạch) chuyển sang bản giữ.
        """
        keep.ensure_one()
        duplicates = (self - keep).filtered(lambda place: place.company_id == keep.company_id)
        if not duplicates:
            raise UserError('Không có địa điểm nào để gộp vào #%s.' % keep.id)

        keep.write(_blank_fill_values(keep, duplicates, FILL_FIELDS))
        if not keep.has_coords:
            donor = duplicates.filtered('has_coords').sorted(
                lambda place: GEO_RANK.get(place.geo_state, 9)
            )[:1]
            if donor:
                keep.write({
                    'latitude': donor.latitude, 'longitude': donor.longitude,
                    'geo_state': donor.geo_state, 'geo_source': donor.geo_source,
                })

        profiles_moved = self._merge_profiles(keep, duplicates)
        moved = self._repoint_references(keep, duplicates)

        names = ', '.join('#%s %s' % (place.id, place.name) for place in duplicates)
        keep.message_post(body='Đã gộp vào địa điểm này: %s.' % names)
        for place in duplicates:
            place.message_post(body='Đã gộp vào #%s %s và lưu trữ.' % (keep.id, keep.name))
        duplicates.write({'active': False})
        return dict(moved, keep_id=keep.id, merged_ids=duplicates.ids,
                    profiles_moved=profiles_moved)

    def _merge_profiles(self, keep, duplicates):
        """Chuyển / lấp thói quen khách từ các bản gộp sang bản giữ. Trả về số bộ đã xử lý."""
        handled = 0
        for place in duplicates:
            profile = place.profile_id
            if not profile:
                continue
            handled += 1
            if not keep.profile_id:
                profile.place_id = keep
                continue
            keep.profile_id._fill_blanks(_write_values(profile, PROFILE_FIELDS))
            profile.unlink()
        return handled

    def _repoint_references(self, keep, duplicates):
        """Chuyển mọi tham chiếu tới bản gộp sang bản giữ. Trả về số bản ghi đã chuyển."""
        env = self.env
        plans = env['hlv.vtracking.plan'].sudo().search([('start_place_id', 'in', duplicates.ids)])
        plans.write({'start_place_id': keep.id})
        vehicles = env['fleet.vehicle'].sudo().search([
            ('dispatch_start_place_id', 'in', duplicates.ids),
        ])
        vehicles.write({'dispatch_start_place_id': keep.id})
        lines = env['hlv.vtracking.plan.line'].sudo().search([('place_id', 'in', duplicates.ids)])
        lines.write({'place_id': keep.id})
        return {
            'plans_moved': len(plans),
            'vehicles_moved': len(vehicles),
            'plan_lines_moved': len(lines),
        }
