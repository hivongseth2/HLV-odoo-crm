"""Địa điểm và thói quen khách cho AI: xem, tạo, sửa, tra toạ độ, gộp trùng, mồi thói quen.

Mọi thao tác GHI để lại một dòng trên chatter của địa điểm, ghi rõ khoá API nào làm — như
các endpoint ghi kế hoạch.
"""

from odoo.addons.hlv_geo_utils.tools.geo_text import normalize_name
from odoo.exceptions import UserError

from ...tools.vtracking_dedup import place_duplicate_groups
from .input_parse import coords_from_body, pick_values
from .serialize import coords_block, iso_datetime

PLACE_FIELDS = ('name', 'partner_id', 'zone_id', 'warehouse_id', 'address', 'note', 'active')
PROFILE_FIELDS = (
    'procedure_required', 'delivery_method', 'default_vehicle_id', 'extra_service_minutes',
    'receiving_from', 'receiving_to', 'payment_method', 'free_note',
)


def profile_block(profile):
    if not profile:
        return None
    return {
        'id': profile.id,
        'procedure_required': profile.procedure_required or 'none',
        'delivery_method': profile.delivery_method or None,
        'needs_truck': profile.needs_truck,
        'default_vehicle_id': profile.default_vehicle_id.id or None,
        'extra_service_minutes': profile.extra_service_minutes or 0,
        'receiving_from': profile.receiving_from or None,
        'receiving_to': profile.receiving_to or None,
        'payment_method': profile.payment_method or None,
        'free_note': profile.free_note or None,
    }


def place_block(place, with_profile=True):
    block = {
        'id': place.id,
        'name': place.name,
        'active': place.active,
        'type_code': place.type_code or None,
        'type_name': place.type_id.name,
        'partner_id': place.partner_id.id or None,
        'partner_name': place.partner_id.display_name or None,
        'root_partner_id': place.partner_id.commercial_partner_id.id or None,
        'zone_id': place.zone_id.id or None,
        'zone_name': place.zone_id.name or None,
        'warehouse_id': place.warehouse_id.id or None,
        'address': place.address or None,
        'address_used': place.address_used or None,
        'coords': coords_block(place.latitude, place.longitude),
        'geo_state': place.geo_state,
        'geo_source': place.geo_source or None,
        'geo_checked_at': iso_datetime(place.geo_checked_at),
        'note': place.note or None,
    }
    if with_profile:
        block['profile'] = profile_block(place.profile_id)
    return block


def list_places(env, company, params):
    """Lọc địa điểm. ``params``: search, type_code, zone_id, geo_state, has_coords (0/1),
    no_zone (1), no_profile (1), no_partner (1), include_archived (1), limit, offset."""
    domain = [('company_id', '=', company.id)]
    if params.get('search'):
        domain += ['|', '|', ('name', 'ilike', params['search']),
                   ('address', 'ilike', params['search']),
                   ('partner_id.name', 'ilike', params['search'])]
    if params.get('type_code'):
        domain.append(('type_id.code', '=', params['type_code']))
    if params.get('zone_id'):
        domain.append(('zone_id', '=', int(params['zone_id'])))
    if params.get('geo_state'):
        domain.append(('geo_state', '=', params['geo_state']))
    if params.get('has_coords') in ('0', '1'):
        domain.append(('has_coords', '=', params['has_coords'] == '1'))
    if params.get('no_zone') == '1':
        domain.append(('zone_id', '=', False))
    if params.get('no_profile') == '1':
        domain.append(('profile_ids', '=', False))
    if params.get('no_partner') == '1':
        domain.append(('partner_id', '=', False))
    Place = env['hlv.vtracking.place']
    if params.get('include_archived') == '1':
        Place = Place.with_context(active_test=False)
    records = Place.search(domain, limit=params['limit'], offset=params['offset'])
    return {
        'total': Place.search_count(domain),
        'places': [place_block(record, with_profile=False) for record in records],
    }


def _type_from_body(env, body):
    code = body.get('type_code') or 'customer'
    place_type = env['hlv.vtracking.place.type'].search([('code', '=', code)], limit=1)
    if not place_type:
        codes = env['hlv.vtracking.place.type'].search([]).mapped('code')
        raise UserError('"type_code" phải là một trong: %s.' % ', '.join(c for c in codes if c))
    return place_type


def create_place(env, company, body, actor):
    if not (body.get('name') or '').strip():
        raise UserError('Thiếu "name".')
    Place = env['hlv.vtracking.place']
    values = pick_values(body, Place, PLACE_FIELDS)
    values.update({'type_id': _type_from_body(env, body).id, 'company_id': company.id})
    place = Place.create(values)
    _apply_coords(place, body)
    place.message_post(body='API (%s): tạo địa điểm.' % actor)
    return place_block(place)


def update_place(place, body, actor):
    values = pick_values(body, place, PLACE_FIELDS)
    if body.get('type_code'):
        values['type_id'] = _type_from_body(place.env, body).id
    if values:
        place.write(values)
    changed = sorted(values)
    if _apply_coords(place, body):
        changed.append('toạ độ')
    if not changed:
        raise UserError('Không có ô nào để sửa. Ô sửa được: %s, type_code, coords.'
                        % ', '.join(PLACE_FIELDS))
    place.message_post(body='API (%s): sửa %s.' % (actor, ', '.join(changed)))
    return place_block(place)


def _apply_coords(place, body):
    """Toạ độ trong body -> ghi tay (``manual``) qua đúng hàm của model. Trả True nếu có ghi."""
    coords = coords_from_body(body)
    if not coords:
        return False
    place.geo_input = '%s, %s' % coords
    place.action_save_manual_geo()
    return True


def geocode_place(place, actor):
    """Tra lại toạ độ (CÓ THỂ TỐN TIỀN). Toạ độ nhập tay thì không tra — giữ nguyên."""
    if place.geo_state == 'manual':
        raise UserError('Địa điểm #%s có toạ độ nhập tay — không tra lại để khỏi đè.' % place.id)
    place._geocode_one()
    place.message_post(body='API (%s): tra lại toạ độ.' % actor)
    return place_block(place)


def confirm_place_geo(place, actor):
    place.action_confirm_geo()
    place.message_post(body='API (%s): duyệt toạ độ.' % actor)
    return place_block(place)


def upsert_profile(place, body, actor):
    """Tạo hoặc sửa thói quen khách của một địa điểm. Chỉ ghi các ô có trong body."""
    Profile = place.env['hlv.vtracking.partner.profile']
    values = pick_values(body, place.profile_id or Profile, PROFILE_FIELDS)
    if not values:
        raise UserError('Không có ô thói quen nào. Ô sửa được: %s.' % ', '.join(PROFILE_FIELDS))
    if place.profile_id:
        place.profile_id.write(values)
    else:
        Profile.create(dict(values, place_id=place.id, company_id=place.company_id.id))
    place.message_post(body='API (%s): sửa thói quen khách (%s).' % (actor, ', '.join(sorted(values))))
    return place_block(place)


def seed_known_profiles(env, company):
    """Mồi thói quen đã biết (bảng trong ``tools/vtracking_habits``) vào các điểm khớp tên."""
    places = env['hlv.vtracking.place'].search([('company_id', '=', company.id)])
    return env['hlv.vtracking.partner.profile'].seed_known(places)


def place_duplicates(env, company):
    """Nhóm địa điểm nghi trùng kèm lý do — ``same_customer`` có thể là hai nhà máy thật."""
    places = env['hlv.vtracking.place'].search([('company_id', '=', company.id)])
    by_id = {place.id: place for place in places}
    rows = [{
        'id': place.id,
        'name_key': normalize_name(place.name),
        'root_partner_id': place.partner_id.commercial_partner_id.id or None,
        'point': (place.latitude, place.longitude) if place.has_coords else None,
        'geo_state': place.geo_state,
        'has_profile': bool(place.profile_id),
        'has_warehouse': bool(place.warehouse_id),
    } for place in places]
    groups = place_duplicate_groups(rows)
    for group in groups:
        group['places'] = [place_block(by_id[item]) for item in group['ids']]
    return {'group_count': len(groups), 'groups': groups}


def merge_places(env, company, keep_id, merge_ids, actor):
    Place = env['hlv.vtracking.place']
    keep = Place.browse(keep_id).exists()
    if not keep or keep.company_id != company:
        raise UserError('Không có địa điểm #%s.' % keep_id)
    wanted = set(merge_ids) - {keep_id}
    duplicates = Place.browse(list(wanted)).exists().filtered(lambda p: p.company_id == company)
    if len(duplicates) != len(wanted):
        raise UserError('Có id trong "merge_ids" không tồn tại hoặc thuộc công ty khác.')
    result = duplicates.merge_into(keep)
    keep.message_post(body='API (%s): gộp %s vào đây.' % (actor, ', '.join('#%s' % i for i in duplicates.ids)))
    result['keep'] = place_block(keep)
    return result
