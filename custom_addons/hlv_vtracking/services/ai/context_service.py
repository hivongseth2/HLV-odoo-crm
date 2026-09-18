"""Bối cảnh chung mà AI cần nắm TRƯỚC khi lập kế hoạch: có những kho nào, xe nào, buổi nào,
định mức tính đường ra sao, và các luật nghiệp vụ không đọc được từ dữ liệu.

Gom vào một lời gọi: đây là thứ gần như không đổi trong ngày, AI gọi một lần đầu phiên
làm việc rồi giữ lại.
"""

from odoo import fields

from .. import plan_payload
from ...tools.vtracking_route import route_params
from .fulfillment_service import STAGES
from .serialize import coords_block

# Luật nghiệp vụ KHÔNG suy ra được từ dữ liệu. Viết ở đây — cạnh code thực thi chúng — thay
# vì chỉ ở file hướng dẫn, để đổi luật thì đổi một chỗ và AI luôn đọc được bản mới nhất.
BUSINESS_RULES = [
    'Đơn vị kế hoạch là (xe, ngày, buổi). Mỗi xe chỉ có MỘT kế hoạch cho mỗi buổi; kế hoạch '
    '"full_day" chiếm cả ngày của xe đó.',
    'Kho xuất theo 3 bước: pick (lấy hàng) → pack (đóng gói) → out (xuất). Chỉ phiếu OUT ở '
    'trạng thái "assigned" mới xếp lên xe ngay được (fulfillment.can_load = true).',
    'Đơn bán chưa có phiếu OUT vẫn xếp được vào kế hoạch bằng sale_order_id; khi kho tạo '
    'phiếu OUT, hệ thống tự gắn phiếu vào dòng kế hoạch đó.',
    'Đơn mua nối với đơn bán qua purchase.order.origin = tên đơn bán. Đơn bán có '
    'supply.supply_state = "waiting" thì hàng CHƯA VỀ ĐỦ — không giao trọn được trước '
    'supply.expected_arrival.',
    'Xe xuất phát từ kho nào thì chỉ nên chở chứng từ của kho đó (so warehouse_id của chứng '
    'từ với start.warehouse_id của kế hoạch).',
    'Đọc delivery.method_note trước khi xếp: "GỬI CPN", "BOOK GRAB", "KHÁCH GHÉ LẤY HÀNG"... '
    'nghĩa là đơn KHÔNG đi xe công ty.',
    'Đọc latest_note / chatter: lời dặn của sale và khách ("ngày 4/9 mới nhận hàng") thường '
    'quyết định ngày giao.',
    'Quãng đường là đường chim bay × hệ số đường bộ, KHÔNG phải đường đi thật. Dùng để so '
    'các phương án với nhau, không dùng để hứa giờ với khách.',
    'Một chứng từ chỉ nằm trong một kế hoạch. Muốn chuyển xe: gỡ khỏi kế hoạch cũ rồi xếp '
    'vào kế hoạch mới.',
]


def build_context(env, company):
    """Toàn bộ bối cảnh tĩnh của công ty gắn với khoá API."""
    return {
        'server_time_utc': fields.Datetime.now().isoformat() + 'Z',
        'today': fields.Date.to_string(fields.Date.context_today(env['hlv.vtracking.plan'])),
        'timezone': env.user.tz or 'Asia/Ho_Chi_Minh',
        'company': {'id': company.id, 'name': company.name, 'currency': company.currency_id.name},
        'sessions': [{'code': code, 'label': label} for code, label in plan_payload.SESSION_LABELS.items()],
        'route_params': route_params(
            company.vtracking_avg_speed_kmh, company.vtracking_minutes_per_stop,
            company.vtracking_road_factor,
        ),
        'fulfillment_stages': [
            {'code': code, 'label': label, 'can_load': can_load}
            for code, (label, can_load) in STAGES.items()
        ],
        'warehouses': warehouse_blocks(env, company),
        'vehicles': vehicle_blocks(env, company),
        'business_rules': BUSINESS_RULES,
    }


def warehouse_blocks(env, company):
    """Các kho của công ty, mỗi kho kèm địa điểm xuất phát tương ứng trên bản đồ (nếu có).

    ``start_place_id`` là giá trị cần truyền khi tạo kế hoạch xuất phát từ kho đó. Kho
    chưa có địa điểm gắn vào thì ``start_place_id`` là None — tạo kế hoạch được nhưng
    không tính được chặng đầu từ kho.
    """
    places = env['hlv.vtracking.place'].search([
        ('company_id', '=', company.id), ('warehouse_id', '!=', False),
    ])
    place_by_warehouse = {}
    for place in places:
        place_by_warehouse.setdefault(place.warehouse_id.id, place)

    blocks = []
    for warehouse in env['stock.warehouse'].search([('company_id', '=', company.id)]):
        place = place_by_warehouse.get(warehouse.id)
        blocks.append({
            'id': warehouse.id,
            'name': warehouse.name,
            'code': warehouse.code,
            'delivery_steps': warehouse.delivery_steps,
            'start_place_id': place.id if place else None,
            'coords': coords_block(place.latitude, place.longitude) if place else None,
        })
    return blocks


def vehicle_blocks(env, company):
    """Các xe lập kế hoạch được (đã bật theo dõi). Vị trí và kế hoạch: xem /fleet."""
    vehicles = env['fleet.vehicle'].search([
        ('vtracking_enabled', '=', True), ('company_id', 'in', [company.id, False]),
    ], order='license_plate')
    return [{
        'id': vehicle.id,
        'license_plate': vehicle.license_plate or None,
        'model': vehicle.model_id.display_name or None,
        'driver': vehicle.driver_id.name or None,
    } for vehicle in vehicles]
