"""Tình hình đội xe trong một ngày: xe đang ở đâu, đã nhận những kế hoạch nào, còn trống
buổi nào.
"""

from .. import plan_payload
from .serialize import iso_date

# Buổi có thể xếp thêm. "Cả ngày" không nằm đây: nó là một kế hoạch chiếm cả hai buổi.
HALF_DAY_SESSIONS = ('morning', 'afternoon')


def free_sessions(planned_sessions):
    """Các buổi còn trống của một xe, từ tập buổi đã có kế hoạch. Hàm thuần.

    Đã có kế hoạch ``full_day`` thì không còn buổi nào. Còn trống cả hai buổi thì trả thêm
    ``full_day`` — xe đó nhận được một chuyến dài cả ngày.
    """
    taken = set(planned_sessions)
    if 'full_day' in taken:
        return []
    free = [session for session in HALF_DAY_SESSIONS if session not in taken]
    if len(free) == len(HALF_DAY_SESSIONS):
        free.append('full_day')
    return free


def fleet_status(env, company, day):
    """Mọi xe đang theo dõi của công ty, kèm kế hoạch trong ngày ``day``.

    Vị trí là vị trí đồng bộ gần nhất (xem ``position_at`` và ``is_stale``), không gọi
    sang vTracking — AI hỏi dồn dập cũng không làm tài khoản vTracking dính giới hạn.
    """
    vehicles = env['fleet.vehicle'].search([
        ('vtracking_enabled', '=', True),
        ('company_id', 'in', [company.id, False]),
    ], order='license_plate')
    plans = plan_payload.plans_by_vehicle(env, vehicles.ids, day)

    items = []
    for vehicle in vehicles:
        vehicle_plans = plans.get(vehicle.id, [])
        item = vehicle._vtracking_map_payload()
        item['capacity'] = vehicle._dispatch_capacity_payload()
        item['plans'] = [
            {key: value for key, value in plan.items() if key != 'lines'}
            for plan in vehicle_plans
        ]
        item['day_load'] = {
            'plan_count': len(vehicle_plans),
            'stop_count': sum(plan['line_count'] for plan in vehicle_plans),
            'amount_total': sum(plan['amount_total'] for plan in vehicle_plans),
            'distance_km': round(sum(plan['distance_km'] for plan in vehicle_plans), 1),
            'total_minutes': sum(plan['total_minutes'] for plan in vehicle_plans),
        }
        item['free_sessions'] = free_sessions(plan['session'] for plan in vehicle_plans)
        items.append(item)
    return {'date': iso_date(day), 'count': len(items), 'vehicles': items}
