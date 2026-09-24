"""Đưa dữ liệu vTracking vào Odoo.

Đây là chỗ DUY NHẤT trong module được vừa gọi mạng vừa đụng ``env``: lớp HTTP
(``vtracking_client``) không biết Odoo, lớp bóc dữ liệu (``tools/vtracking_parse``) là
hàm thuần. Mọi thứ nối hai đầu đó lại nằm ở đây.

Nguyên tắc xuyên suốt: **chỉ xe được khai trong Odoo mới được đồng bộ.** Đội xe trên
vTracking có thể gồm xe của công ty khác trong cùng tài khoản; kéo hết về là ghi vào
Odoo những xe không ai quản.
"""

import logging

import pytz

from odoo import fields

from ..tools.vtracking_parse import (
    day_bounds_ms,
    journey_distance_km,
    normalize_plate,
    parse_journey_logs,
    parse_vehicle,
)
from .vtracking_client import VTrackingClient, VTrackingError

_logger = logging.getLogger(__name__)

DEFAULT_TZ = 'Asia/Ho_Chi_Minh'


def get_client(company):
    """Client dựng từ cấu hình của một ``res.company``. Ném VTrackingError nếu thiếu."""
    return VTrackingClient(
        base_url=company.vtracking_base_url,
        api_key=company.vtracking_api_key,
        verify_ssl=company.vtracking_verify_ssl,
        timeout=company.vtracking_timeout or 20,
    )


def tracked_vehicles(env, company=None):
    """Các xe đã bật theo dõi và có biển số — tập xe duy nhất module này đụng tới."""
    domain = [('vtracking_enabled', '=', True), ('license_plate', '!=', False)]
    if company:
        domain.append(('company_id', 'in', [company.id, False]))
    return env['fleet.vehicle'].sudo().search(domain)


def fetch_remote_vehicles(env, company=None):
    """TOÀN BỘ xe trên tài khoản vTracking, đã bóc sẵn thành dict phẳng.

    Khác ``sync_vehicles`` ở chỗ không lọc theo xe đã khai trong Odoo: đây là nguồn cho
    màn nhập xe, mà mục đích của màn đó chính là thấy những xe Odoo **chưa** có.

    Xe trùng biển số trong chính phản hồi của vTracking chỉ giữ bản ghi đầu — nếu không,
    màn nhập sẽ mời người dùng tạo hai xe cùng biển.
    """
    company = company or env.company
    client = get_client(company)
    by_key = {}
    for raw in client.iter_vehicles(expand=company.vtracking_expand_children):
        parsed = parse_vehicle(raw)
        if parsed and parsed['plate_key'] not in by_key:
            by_key[parsed['plate_key']] = parsed
    return list(by_key.values())


def sync_vehicles(env, company=None):
    """Kéo vị trí hiện tại của các xe đang theo dõi về ``fleet.vehicle``.

    Một request cho cả đội (lọc bằng tham số ``plates``) thay vì mỗi xe một request:
    tài liệu không công bố hạn mức, chỉ có mã 429, nên xin ít lần nhất có thể.

    Trả về dict thống kê ``{matched, unmatched_plates, missing_plates, total}`` để màn
    cấu hình và cron cùng báo cáo được một kiểu. Biển số không ghép được KHÔNG bị nuốt
    lặng — đó là lỗi khai báo, phải hiện ra mới sửa được.
    """
    company = company or env.company
    vehicles = tracked_vehicles(env, company)
    if not vehicles:
        return {'matched': 0, 'unmatched_plates': [], 'missing_plates': [], 'total': 0}

    client = get_client(company)
    by_plate_key = {vehicle.plate_key: vehicle for vehicle in vehicles if vehicle.plate_key}
    plates = [vehicle.license_plate for vehicle in vehicles]

    matched, unmatched = 0, []
    seen_keys = set()
    now = fields.Datetime.now()

    for raw in client.iter_vehicles(
        plates=plates, expand=company.vtracking_expand_children,
    ):
        parsed = parse_vehicle(raw)
        if not parsed:
            continue
        vehicle = by_plate_key.get(parsed['plate_key'])
        if not vehicle:
            unmatched.append(parsed['license_plate'])
            continue
        seen_keys.add(parsed['plate_key'])
        vehicle.write(_vehicle_values(parsed, now))
        matched += 1

    missing = [
        vehicle.license_plate
        for vehicle in vehicles
        if vehicle.plate_key and vehicle.plate_key not in seen_keys
    ]
    if unmatched or missing:
        _logger.info(
            'vTracking: %s xe khớp; %s biển số vTracking không có trong Odoo; '
            '%s xe khai trong Odoo mà vTracking không trả về.',
            matched, len(unmatched), len(missing),
        )
    return {
        'matched': matched,
        'unmatched_plates': unmatched,
        'missing_plates': missing,
        'total': len(vehicles),
    }


def _vehicle_values(parsed, synced_at):
    """dict đã bóc -> vals ghi vào ``fleet.vehicle``.

    Toạ độ chỉ ghi khi có ĐỦ cả hai: ghi mỗi vĩ độ sẽ tạo ra một điểm giữa Đại Tây Dương
    trên bản đồ. Trường nào API không trả thì để nguyên giá trị cũ thay vì xoá trắng —
    xe mất sóng vẫn nên thấy vị trí biết lần cuối.
    """
    values = {
        'vtracking_id': parsed['vtracking_id'],
        'vtracking_synced_at': synced_at,
        'vtracking_status': parsed['status'] or False,
        'vtracking_status_since': parsed['status_since'] or False,
        'vtracking_geocoding': parsed['geocoding'] or False,
        'vtracking_driver_name': parsed['driver_name'] or False,
        'vtracking_alarm_codes': ','.join(parsed['alarms']) or False,
    }
    if parsed['latitude'] is not None and parsed['longitude'] is not None:
        values['vtracking_latitude'] = parsed['latitude']
        values['vtracking_longitude'] = parsed['longitude']
    for key, field in (
        ('speed', 'vtracking_speed'),
        ('direction', 'vtracking_direction'),
        ('odometer', 'vtracking_odometer'),
    ):
        if parsed[key] is not None:
            values[field] = parsed[key]
    for key, field in (('acc', 'vtracking_acc'), ('door', 'vtracking_door')):
        # None = xe không lắp cảm biến. Ghi 'unknown' chứ không ghi False, để không hiển
        # thị "cửa đóng" cho xe vốn không có cảm biến cửa.
        values[field] = {True: 'on', False: 'off'}.get(parsed[key], 'unknown')
    if parsed['position_at']:
        values['vtracking_position_at'] = parsed['position_at']
    return values


def fetch_journey(env, vehicle, day, store=True):
    """Lấy hành trình của MỘT xe trong MỘT ngày địa phương.

    Trả về ``{'pings': [...], 'distance_km': float, 'pages': int}``. ``store=False``
    dùng cho màn xem lại trên bản đồ: chỉ cần vẽ, không cần ghi thêm bản ghi vào CSDL.

    Xe chưa có UUID vTracking thì đồng bộ danh sách xe trước — UUID chỉ lấy được từ
    endpoint danh sách, không suy ra được từ biển số.
    """
    if not vehicle.vtracking_id:
        raise VTrackingError(
            'Xe %s chưa có mã vTracking. Bấm "Đồng bộ ngay" ở cấu hình để ghép biển số trước.'
            % (vehicle.license_plate or vehicle.display_name)
        )
    company = vehicle.company_id or env.company
    client = get_client(company)
    tz = pytz.timezone(env.user.tz or DEFAULT_TZ)
    start_ms, end_ms = day_bounds_ms(day, tz)

    pings, distance, pages = [], 0.0, 0
    for payload in client.iter_journey_pages(
        vehicle.vtracking_id, start_ms=start_ms, end_ms=end_ms,
    ):
        pings.extend(parse_journey_logs(payload))
        distance += journey_distance_km(payload)
        pages += 1

    if store and pings:
        _store_positions(env, vehicle, pings)
    return {'pings': pings, 'distance_km': distance, 'pages': pages}


def _store_positions(env, vehicle, pings):
    """Ghi ping vào ``hlv.vtracking.position``, bỏ qua ping đã có.

    Chống trùng bằng cách đọc trước các mốc thời gian đã lưu trong khoảng đang ghi: cùng
    một ngày có thể được lấy lại nhiều lần (cron chạy lại, người bấm tải lại) và mỗi lần
    lại nhân đôi dữ liệu thì mọi phép đếm sau này đều sai.
    """
    Position = env['hlv.vtracking.position'].sudo()
    first, last = pings[0]['ts'], pings[-1]['ts']
    existing = set(Position.search([
        ('vehicle_id', '=', vehicle.id),
        ('ts', '>=', first),
        ('ts', '<=', last),
    ]).mapped('ts'))

    values = [{
        'vehicle_id': vehicle.id,
        'ts': ping['ts'],
        'latitude': ping['latitude'],
        'longitude': ping['longitude'],
        'speed': ping['speed'] or 0.0,
        'direction': ping['direction'] or 0.0,
        'status': ping['status'] or False,
        'geocoding': ping['geocoding'] or False,
    } for ping in pings if ping['ts'] not in existing]

    if values:
        Position.create(values)
    return len(values)


def sync_journeys_for_day(env, day, company=None):
    """Kéo hành trình của mọi xe đang theo dõi cho một ngày. Dùng cho cron.

    Mỗi xe ``commit`` riêng: một xe lỗi (429, mất mạng, UUID sai) không được kéo theo
    các xe đã lấy xong trong cùng transaction.
    """
    company = company or env.company
    vehicles = tracked_vehicles(env, company).filtered('vtracking_id')
    ok, failed = 0, []
    for vehicle in vehicles:
        try:
            fetch_journey(env, vehicle, day, store=True)
            env.cr.commit()
            ok += 1
        except (VTrackingError, ValueError) as exc:
            env.cr.rollback()
            failed.append(vehicle.license_plate)
            _logger.warning('vTracking: lấy hành trình xe %s ngày %s lỗi: %s',
                            vehicle.license_plate, day, exc)
    _logger.info('vTracking: hành trình ngày %s — %s xe xong, %s xe lỗi.', day, ok, len(failed))
    return {'ok': ok, 'failed': failed}


def match_plate(env, plate):
    """Tìm xe Odoo theo biển số vTracking. Trả về recordset rỗng nếu không có.

    Dùng khoá đã chuẩn hoá thay vì so chuỗi thô: ``51C-775.77`` và ``51C77577`` là một xe.
    """
    key = normalize_plate(plate)
    if not key:
        return env['fleet.vehicle'].browse()
    return env['fleet.vehicle'].sudo().search([('plate_key', '=', key)], limit=1)
