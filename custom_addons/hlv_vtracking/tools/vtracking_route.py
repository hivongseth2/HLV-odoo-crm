"""Ước lượng quãng đường và thời gian của một lộ trình — hàm thuần, vào gì ra nấy.

Không đụng ``self.env``, không gọi mạng. Model kế hoạch, màn xem trước của wizard và API
cho AI đều phải tính qua đây: ba chỗ tự nhân hệ số riêng là ba con số km khác nhau cho
cùng một chuyến.

Quãng đường = đường chim bay nối các điểm theo thứ tự × hệ số đường bộ. KHÔNG phải quãng
đường thật trên bản đồ — dùng để so các phương án với nhau, không dùng để hứa giờ với khách.
"""

from odoo.addons.hlv_geo_utils.tools.geo_distance import haversine_km

DEFAULT_SPEED_KMH = 35.0
DEFAULT_MINUTES_PER_STOP = 10
DEFAULT_ROAD_FACTOR = 1.3


def route_params(speed_kmh=None, minutes_per_stop=None, road_factor=None):
    """Bộ tham số tính lộ trình, thay giá trị rỗng/0 bằng mặc định.

    Tốc độ 0 sẽ gây chia cho 0, hệ số 0 sẽ cho quãng đường 0 — coi cả hai là "chưa cấu
    hình" chứ không phải giá trị hợp lệ.
    """
    return {
        'speed_kmh': speed_kmh or DEFAULT_SPEED_KMH,
        'minutes_per_stop': minutes_per_stop or DEFAULT_MINUTES_PER_STOP,
        'road_factor': road_factor or DEFAULT_ROAD_FACTOR,
    }


def estimate_legs(start, stops, params):
    """Từng chặng của lộ trình, kèm giờ tới cộng dồn.

    start: tuple ``(lat, lng)`` điểm xuất phát, hoặc None.
    stops: list tuple ``(lat, lng)`` theo đúng thứ tự ghé; phần tử None = điểm CHƯA có toạ
        độ. Điểm thiếu toạ độ vẫn tính thời gian giao (xe vẫn phải ghé) nhưng không có
        quãng đường riêng.
    params: kết quả của ``route_params``.

    Trả về list dict, mỗi phần tử ứng với MỘT điểm trong ``stops``::

        {'leg_km': float|None,            # quãng đường từ điểm trước tới điểm này
         'leg_minutes': int|None,         # thời gian chạy chặng đó
         'arrive_offset_minutes': int,    # phút tính từ lúc xuất phát tới khi TỚI điểm này
         'depart_offset_minutes': int}    # ... tới khi RỜI điểm này

    ``leg_km`` là None với điểm thiếu toạ độ. Điểm kế tiếp được đo từ điểm GẦN NHẤT CÓ
    TOẠ ĐỘ trước nó (nối thẳng qua điểm thiếu): theo bất đẳng thức tam giác đó là cận dưới
    chặt nhất có thể có, và khớp với cách ``total_path_km`` của hlv_geo_utils bỏ qua điểm
    lỗi. Vì vậy khi có điểm thiếu toạ độ, mọi con số ở đây là CẬN DƯỚI.
    """
    legs = []
    previous = start
    clock = 0
    for stop in stops:
        leg_km = None
        leg_minutes = None
        if stop and previous:
            straight = haversine_km(previous, stop)
            if straight is not None:
                leg_km = round(straight * params['road_factor'], 1)
                leg_minutes = int(round(leg_km / params['speed_kmh'] * 60))
        clock += leg_minutes or 0
        arrive = clock
        clock += params['minutes_per_stop']
        legs.append({
            'leg_km': leg_km,
            'leg_minutes': leg_minutes,
            'arrive_offset_minutes': arrive,
            'depart_offset_minutes': clock,
        })
        # Điểm thiếu toạ độ không dời mốc đo: chặng kế tiếp vẫn đo từ điểm có toạ độ
        # gần nhất phía trước.
        if stop:
            previous = stop
    return legs


def estimate_route(start, stops, params):
    """Tổng hợp cả lộ trình.

    Tham số như ``estimate_legs``. Trả về dict::

        {'distance_km', 'drive_minutes', 'service_minutes', 'total_minutes',
         'missing_coords_count', 'legs'}

    Lộ trình rỗng trả về toàn số 0 và ``legs`` rỗng.
    """
    legs = estimate_legs(start, stops, params)
    distance = round(sum(leg['leg_km'] or 0.0 for leg in legs), 1)
    drive = sum(leg['leg_minutes'] or 0 for leg in legs)
    service = params['minutes_per_stop'] * len(stops)
    return {
        'distance_km': distance,
        'drive_minutes': drive,
        'service_minutes': service,
        'total_minutes': drive + service,
        'missing_coords_count': sum(1 for stop in stops if not stop),
        'legs': legs,
    }


def format_minutes(minutes):
    """Số phút -> "2h15'" cho dễ đọc. 0 hoặc None trả về "—"."""
    if not minutes:
        return '—'
    hours, mins = divmod(int(minutes), 60)
    if not hours:
        return "%d'" % mins
    return "%dh%02d'" % (hours, mins)
