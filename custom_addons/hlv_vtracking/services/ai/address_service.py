"""Kho toạ độ (``hlv.vtracking.address``) cho AI: xem, sửa toạ độ, tra lại, gộp trùng.

Mọi luật gộp/tìm trùng nằm ở ``tools/vtracking_dedup`` và ``models/vtracking_address_merge``;
file này chỉ nối API với chúng.
"""

from odoo.exceptions import UserError

from ...tools.vtracking_dedup import address_duplicate_groups
from .input_parse import coords_from_body
from .serialize import iso_datetime

GEO_STATES = ('pending_review', 'confirmed', 'manual', 'failed')


def address_block(record):
    """Một bản ghi toạ độ ở dạng dict. Toạ độ ngoài Việt Nam trả None — nó sai chắc chắn."""
    usable = record.has_coords and not record.outside_vietnam
    return {
        'id': record.id,
        'raw_address': record.raw_address,
        'normalized_address': record.normalized_address or None,
        'latitude': record.latitude if usable else None,
        'longitude': record.longitude if usable else None,
        'geo_state': record.geo_state,
        'geo_source': record.geo_source or None,
        'outside_vietnam': record.outside_vietnam,
        'alias_of_id': record.alias_of_id.id or None,
        'hit_count': record.hit_count,
        'last_used_at': iso_datetime(record.last_used_at),
        'plan_line_count': record.env['hlv.vtracking.plan.line'].sudo().search_count(
            [('address_id', '=', record.id)]
        ),
    }


def list_addresses(env, company, params):
    """Lọc kho toạ độ. ``params``: search, geo_state, has_coords (0/1), outside_vietnam (1),
    include_aliases (1), limit, offset."""
    domain = [('company_id', '=', company.id)]
    if params.get('search'):
        domain += ['|', ('raw_address', 'ilike', params['search']),
                   ('normalized_address', 'ilike', params['search'])]
    if params.get('geo_state'):
        if params['geo_state'] not in GEO_STATES:
            raise UserError('"geo_state" phải là một trong: %s.' % ', '.join(GEO_STATES))
        domain.append(('geo_state', '=', params['geo_state']))
    if params.get('has_coords') in ('0', '1'):
        domain.append(('has_coords', '=', params['has_coords'] == '1'))
    if params.get('outside_vietnam') == '1':
        domain.append(('outside_vietnam', '=', True))
    if params.get('include_aliases') != '1':
        domain.append(('alias_of_id', '=', False))
    Address = env['hlv.vtracking.address']
    records = Address.search(domain, limit=params['limit'], offset=params['offset'])
    return {'total': Address.search_count(domain), 'addresses': [address_block(r) for r in records]}


def update_address(record, body):
    """Sửa toạ độ tay (``coords`` hoặc ``latitude``/``longitude``) và/hoặc duyệt (``confirm``).

    Toạ độ nhập tay được đánh dấu ``manual``: máy không bao giờ đè lên nữa.
    """
    coords = coords_from_body(body)
    if coords:
        record.write({
            'latitude': coords[0], 'longitude': coords[1],
            'geo_source': 'manual', 'geo_state': 'manual', 'geo_input': False,
        })
    elif body.get('confirm'):
        if not record.has_coords:
            raise UserError('Địa chỉ #%s chưa có toạ độ để duyệt.' % record.id)
        record.action_confirm()
    else:
        raise UserError('Cần "coords" (hoặc "latitude"/"longitude") hoặc "confirm": true.')
    return address_block(record)


def geocode_address(record):
    """Tra lại toạ độ (CÓ THỂ TỐN TIỀN). Toạ độ nhập tay thì không tra — giữ nguyên."""
    if record.geo_state == 'manual':
        raise UserError('Địa chỉ #%s có toạ độ nhập tay — không tra lại để khỏi đè.' % record.id)
    record.action_geocode_retry()
    return address_block(record)


def address_duplicates(env, company):
    """Nhóm địa chỉ nghi trùng, kèm nội dung từng bản để người xem quyết."""
    records = env['hlv.vtracking.address'].search([
        ('company_id', '=', company.id), ('alias_of_id', '=', False),
    ])
    by_id = {record.id: record for record in records}
    rows = [{
        'id': record.id,
        'raw_address': record.raw_address,
        'point': (record.latitude, record.longitude) if record.has_coords else None,
        'geo_state': record.geo_state,
        'hit_count': record.hit_count,
    } for record in records]
    groups = address_duplicate_groups(rows)
    for group in groups:
        group['addresses'] = [address_block(by_id[item]) for item in group['ids']]
    return {'group_count': len(groups), 'groups': groups}


def merge_addresses(env, company, keep_id, merge_ids):
    Address = env['hlv.vtracking.address']
    keep = Address.browse(keep_id).exists()
    if not keep or keep.company_id != company:
        raise UserError('Không có địa chỉ #%s.' % keep_id)
    wanted = set(merge_ids) - {keep_id}
    duplicates = Address.browse(list(wanted)).exists().filtered(lambda r: r.company_id == company)
    if len(duplicates) != len(wanted):
        raise UserError('Có id trong "merge_ids" không tồn tại hoặc thuộc công ty khác.')
    result = duplicates.merge_into(keep)
    result['keep'] = address_block(keep)
    return result
