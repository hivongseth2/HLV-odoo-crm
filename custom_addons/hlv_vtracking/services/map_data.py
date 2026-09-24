"""Dựng dữ liệu cho màn bản đồ đội xe.

Tách khỏi model ``fleet.vehicle``: đây là việc gom dữ liệu của ba model (xe, địa điểm, kế
hoạch) để trình bày, không phải quy tắc của riêng xe.
"""

from . import plan_payload


def build_map_data(env, stale_minutes):
    """Toàn bộ dữ liệu một lần vẽ bản đồ cần: cấu hình tile, xe kèm kế hoạch, và địa điểm.

    Gộp vào một lời gọi thay vì ba: bản đồ tự tải lại theo chu kỳ, mỗi chu kỳ thêm một
    request là thêm tải cho thứ gần như không đổi.

    Địa điểm chỉ trả về cái ĐÃ có toạ độ — địa điểm chưa tra được là việc xử lý ở màn quản
    lý địa điểm, không phải thứ để nhìn trên bản đồ.
    """
    company = env.company
    vehicles = env['fleet.vehicle'].sudo().search([
        ('vtracking_enabled', '=', True),
        ('company_id', 'in', [company.id, False]),
    ], order='license_plate')
    places = env['hlv.vtracking.place'].sudo().search([
        ('has_coords', '=', True),
        ('company_id', '=', company.id),
    ])
    place_types = env['hlv.vtracking.place.type'].sudo().search([])

    # Kế hoạch của hôm nay, gắn thẳng vào từng xe: popup xe cần đọc ngay, không nên bắt
    # trình duyệt tự ghép hai danh sách.
    plans = plan_payload.plans_by_vehicle(env, vehicles.ids)
    vehicle_payloads = []
    for vehicle in vehicles:
        payload = vehicle._vtracking_map_payload()
        payload['plans'] = plans.get(vehicle.id, [])
        vehicle_payloads.append(payload)

    return {
        'tile_url': company.vtracking_map_tile_url or '',
        'tile_attribution': company.vtracking_map_attribution or '',
        'stale_minutes': stale_minutes,
        'vehicles': vehicle_payloads,
        'places': [place._map_payload() for place in places],
        'place_types': [{
            'id': place_type.id,
            'name': place_type.name,
            'color': place_type.color,
            'size': place_type.size,
            'visible_by_default': place_type.visible_by_default,
        } for place_type in place_types],
    }
