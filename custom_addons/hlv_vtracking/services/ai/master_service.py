"""Dữ liệu nền còn lại cho AI: cụm tuyến (định mức), xe (chuyên chở + phân công), tài xế.

Sửa định mức cụm là sửa giờ của MỌI kế hoạch nháp dùng cụm đó — nên mỗi lần sửa đều trả
lại cả giá trị cũ lẫn mới để bên gọi nói lại được với người dùng mình vừa đổi gì.
"""

from odoo.exceptions import UserError

from ..vtracking_calibration import calibrate_company
from .input_parse import pick_values

ZONE_FIELDS = (
    'name', 'code', 'hub_to_first_minutes', 'median_leg_minutes', 'return_minutes',
    'max_stops', 'min_stops_worth_trip', 'warehouse_id', 'note', 'active',
)
VEHICLE_FIELDS = (
    'dispatch_role', 'dispatch_payload_kg', 'dispatch_cargo_length_m', 'dispatch_cargo_width_m',
    'dispatch_cargo_height_m', 'dispatch_max_item_length_m', 'dispatch_max_pieces',
    'dispatch_note', 'dispatch_driver_user_id', 'dispatch_start_place_id',
)


def zone_block(zone):
    return {
        'id': zone.id,
        'name': zone.name,
        'code': zone.code or None,
        'hub_to_first_minutes': zone.hub_to_first_minutes,
        'median_leg_minutes': zone.median_leg_minutes,
        'return_minutes': zone.return_minutes,
        'max_stops': zone.max_stops,
        'min_stops_worth_trip': zone.min_stops_worth_trip,
        'calibration': {
            kind: {
                'measured': zone['calib_%s_median' % kind] or None,
                'samples': zone['calib_%s_count' % kind],
                'suggest': zone['calib_%s_suggest' % kind] or None,
            } for kind in ('hub', 'leg', 'return')
        },
        'calibration_plan_count': zone.calib_plan_count,
        'has_suggestion': zone.calib_has_suggestion,
    }


def update_zone(zone, body):
    before = zone_block(zone)
    values = pick_values(body, zone, ZONE_FIELDS)
    if not values:
        raise UserError('Không có ô nào để sửa. Ô sửa được: %s.' % ', '.join(ZONE_FIELDS))
    zone.write(values)
    return {'before': before, 'after': zone_block(zone)}


def apply_zone_calibration(zone):
    if not zone.calib_has_suggestion:
        raise UserError('Cụm "%s" chưa có đề xuất nào (chưa đủ mẫu hoặc lệch không đáng kể).'
                        % zone.name)
    before = zone_block(zone)
    zone.action_apply_calibration()
    return {'before': before, 'after': zone_block(zone), 'applied': zone.calib_applied_note}


def recalibrate(env, company):
    calibrate_company(env, company)
    zones = env['hlv.vtracking.zone'].search([('company_id', '=', company.id)])
    return {'zones': [zone_block(zone) for zone in zones]}


def update_vehicle(vehicle, body):
    """Sửa chuyên chở + phân công của xe. Khoá ngắn không có tiền tố cũng nhận:
    ``role`` = ``dispatch_role``, ``driver_user_id`` = ``dispatch_driver_user_id``..."""
    body = {
        (key if key.startswith('dispatch_') else 'dispatch_%s' % key): value
        for key, value in body.items()
    }
    values = pick_values(body, vehicle, VEHICLE_FIELDS)
    if not values:
        raise UserError('Không có ô nào để sửa. Ô sửa được: %s.' % ', '.join(VEHICLE_FIELDS))
    vehicle.write(values)
    return {
        'id': vehicle.id,
        'license_plate': vehicle.license_plate,
        'capacity': vehicle._dispatch_capacity_payload(),
        'assignment': vehicle._dispatch_assignment_payload(),
    }


def list_drivers(env, company):
    """Tài khoản có ``shipper_name`` — người chọn được làm tài xế cho xe, kèm xe đang gắn."""
    users = env['res.users'].search([
        ('shipper_name', '!=', False), ('company_ids', 'in', company.id),
    ])
    vehicles = env['fleet.vehicle'].search([('dispatch_driver_user_id', 'in', users.ids)])
    vehicle_by_user = {vehicle.dispatch_driver_user_id.id: vehicle for vehicle in vehicles}
    return {'drivers': [{
        'user_id': user.id,
        'shipper_name': user.shipper_name,
        'login': user.login,
        'vehicle_id': vehicle_by_user[user.id].id if user.id in vehicle_by_user else None,
        'vehicle_plate': vehicle_by_user[user.id].license_plate if user.id in vehicle_by_user else None,
    } for user in users]}
