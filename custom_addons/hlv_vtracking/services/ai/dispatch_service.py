"""Góc nhìn ĐIỀU PHỐI của một đơn bán: vướng gì, thuộc cụm nào, giao xong có phải quay lại.

Ba câu hỏi này Odoo không trả lời được bằng một field nào, mà AI phải biết TRƯỚC khi xếp
xe. Trước đây chúng nằm trong đầu người điều phối; giờ nằm ở đây.

Nguyên tắc tiền bạc: **không gọi geocoder.** Endpoint liệt kê đơn có thể bị gọi hàng trăm
lần một ngày; mỗi lần tra toạ độ là một lần trả tiền. Chỉ đọc toạ độ đã có sẵn trong kho.
Đơn chưa có toạ độ thì lùi về cụm của điểm giao gắn với khách, và đánh dấu là ĐOÁN.
"""

from datetime import date

from odoo import fields

from ...tools.vtracking_blocking import blocking_flags, has_hard_block
from ...tools.vtracking_planning import DEFAULT_ZONE_MATCH_KM, nearest_zone
from . import supply_service

# Khách còn đơn khác sắp có hàng trong ngần này ngày thì giao hôm nay là sẽ phải quay lại.
# 2 ngày: ngắn hơn thì bỏ sót, dài hơn thì đơn nào cũng "rủi ro" và cảnh báo mất tác dụng.
DEFAULT_REVISIT_DAYS = 2


def zone_samples(env, company):
    """Các điểm giao đã biết chắc thuộc cụm nào — tập mẫu để so khoảng cách.

    Đọc MỘT lần cho cả trang đơn. Mỗi đơn một truy vấn thì endpoint liệt kê sẽ ì.
    """
    places = env['hlv.vtracking.place'].sudo().search([
        ('zone_id', '!=', False), ('has_coords', '=', True), ('company_id', '=', company.id),
    ])
    return [(place.zone_id.id, (place.latitude, place.longitude)) for place in places]


def dispatch_block(order, place, coords, samples, near_km=DEFAULT_ZONE_MATCH_KM):
    """Phần "điều phối" của một đơn: ``blocking`` + ``zone`` + ghi chú cho tài xế.

    :param order: ``sale.order`` một bản ghi
    :param place: ``hlv.vtracking.place`` của khách (recordset, có thể rỗng)
    :param coords: dict toạ độ ĐÃ CÓ SẴN trong kho toạ độ, hoặc None — không tra mới
    :param samples: kết quả ``zone_samples`` dùng chung cho cả trang
    """
    profile = place.profile_id if place else None
    channel = order._vtracking_delivery_channel() or (
        profile.delivery_method if profile else None
    )
    flags = blocking_flags(profile.procedure_required if profile else None, channel)
    soft = [flag for flag in flags if not flag['hard']]
    return {
        'blocking': flags,
        'blocked': has_hard_block(flags),
        'delivery_channel': channel or None,
        # Cờ mềm nào cũng có nghĩa "không cần xe công ty" — xem vtracking_blocking.
        'needs_truck': not soft,
        'zone': zone_block(place, coords, samples, near_km),
        'place_id': place.id if place else None,
        'driver_note': (profile.free_note or None) if profile else None,
    }


def zone_block(place, coords, samples, near_km):
    """Cụm tuyến của đơn, suy từ TOẠ ĐỘ trước hết. None khi không suy được.

    ``source``: ``coords`` (tin được) · ``place`` (đoán theo khách).
    ``uncertain=True`` khi điểm mẫu gần nhất vẫn xa hơn ngưỡng, hoặc khi phải đoán theo
    khách — vì lần này khách có thể giao ở một nơi khác.
    """
    point = (coords['latitude'], coords['longitude']) if coords else None
    zone_id, distance, confident = nearest_zone(point, samples, near_km)
    if zone_id and place:
        zone = place.env['hlv.vtracking.zone'].browse(zone_id).exists()
        return {'id': zone_id, 'name': zone.name or None, 'source': 'coords',
                'distance_km': distance, 'uncertain': not confident}
    if zone_id:
        return {'id': zone_id, 'name': None, 'source': 'coords',
                'distance_km': distance, 'uncertain': not confident}
    fallback = place.zone_id if place else None
    if not fallback:
        return None
    return {'id': fallback.id, 'name': fallback.name, 'source': 'place',
            'distance_km': None, 'uncertain': True}


def revisit_map(env, company, orders, days=DEFAULT_REVISIT_DAYS):
    """``{order.id: dict}`` — khách của đơn này còn đơn KHÁC sắp có hàng trong ``days`` ngày.

    Vì sao quan trọng: giao hôm nay rồi mai hàng của đơn kia mới về thì xe phải chạy lại
    đúng chỗ đó. Chờ một hôm gộp hai đơn vào một chuyến là tiết kiệm nguyên một lượt —
    nhưng chỉ thấy được khi nhìn TẤT CẢ đơn của khách, không phải nhìn từng đơn.

    Một truy vấn cho cả trang. Đơn không có rủi ro thì không có mặt trong kết quả.
    """
    roots = orders.mapped('partner_id.commercial_partner_id')
    if not roots:
        return {}
    siblings = env['sale.order'].search([
        ('company_id', '=', company.id),
        ('partner_id.commercial_partner_id', 'in', roots.ids),
        ('state', 'in', ('sale', 'done')),
        ('delivery_status', '!=', 'full'),
        ('id', 'not in', orders.ids),
    ])
    if not siblings:
        return {}

    purchases = supply_service.purchases_by_order_name(env, siblings.mapped('name'))
    today = fields.Date.context_today(siblings[0])
    waiting_by_root = {}
    for sibling in siblings:
        supply = supply_service.supply_summary(purchases.get(sibling.name))
        arrival = supply.get('expected_arrival_date')
        if supply['supply_state'] != 'waiting' or not arrival:
            continue
        waiting_by_root.setdefault(
            sibling.partner_id.commercial_partner_id.id, [],
        ).append({
            'order_id': sibling.id,
            'order_name': sibling.name,
            'expected_arrival_date': arrival,
        })

    result = {}
    for order in orders:
        soon = [
            item for item in waiting_by_root.get(order.partner_id.commercial_partner_id.id, [])
            if _within(item['expected_arrival_date'], today, days)
        ]
        if soon:
            result[order.id] = {
                'within_days': days,
                'other_orders': sorted(soon, key=lambda item: item['expected_arrival_date']),
            }
    return result


def _within(arrival_date, today, days):
    """Ngày về (chuỗi ISO) có nằm trong khoảng hôm nay → ``days`` ngày tới không.

    Ngày đã qua trả False: hàng lẽ ra về hôm kia mà chưa về thì đó là đơn trễ, một vấn đề
    khác, không phải "sắp có hàng".
    """
    try:
        parsed = date.fromisoformat(arrival_date)
    except (TypeError, ValueError):
        return False
    return 0 <= (parsed - today).days <= days
