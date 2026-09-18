"""Ước lượng quãng đường và thời gian của một lộ trình — hàm thuần, vào gì ra nấy.

Không đụng ``self.env``, không gọi mạng. Model kế hoạch, màn xem trước của wizard và API
cho AI đều phải tính qua đây: ba chỗ tự nhân hệ số riêng là ba con số km khác nhau cho
cùng một chuyến.

**Quãng đường** = đường chim bay nối các điểm × hệ số đường bộ. KHÔNG phải quãng đường
thật — dùng để so các phương án, không dùng để hứa giờ với khách.

**Thời gian** có hai cách tính, ưu tiên cách thứ nhất:

1. **Định mức đo được của cụm tuyến** (``hub_to_first_minutes`` / ``median_leg_minutes``).
   Chính xác hơn vì đo từ 332 chuyến thật. **Mỗi chặng ĐÃ GỒM bốc dỡ và ký nhận tại điểm**
   — nên không cộng thêm ``minutes_per_stop``, cộng là tính hai lần.
2. Suy từ quãng đường ÷ tốc độ trung bình — dùng khi điểm chưa gán cụm. Cách này chỉ ra
   thời gian CHẠY thuần nên phải cộng ``minutes_per_stop`` cho thời gian đứng tại điểm.

Cách 1 tồn tại vì đối chiếu kế hoạch với thực tế ngày 11/09 bắt được rằng dùng một con số
chung cho mọi cụm là sai: Nhơn Trạch 40 phút còn Long Thành 57 phút.
"""

from odoo.addons.hlv_geo_utils.tools.geo_distance import haversine_km

DEFAULT_SPEED_KMH = 35.0
DEFAULT_MINUTES_PER_STOP = 10
DEFAULT_ROAD_FACTOR = 1.3


def route_params(speed_kmh=None, minutes_per_stop=None, road_factor=None, zone=None):
    """Bộ tham số tính lộ trình.

    speed_kmh / minutes_per_stop / road_factor: định mức chung của công ty. Giá trị rỗng
        hoặc 0 bị thay bằng mặc định — tốc độ 0 gây chia cho 0, hệ số 0 cho quãng đường 0,
        cả hai đều là "chưa cấu hình" chứ không phải giá trị hợp lệ.
    zone: dict định mức của cụm (``hlv.vtracking.zone.route_params()``), hoặc None. Có
        cụm thì thời gian chạy lấy theo định mức cụm; quãng đường vẫn tính theo toạ độ.
    """
    params = {
        'speed_kmh': speed_kmh or DEFAULT_SPEED_KMH,
        'minutes_per_stop': minutes_per_stop or DEFAULT_MINUTES_PER_STOP,
        'road_factor': road_factor or DEFAULT_ROAD_FACTOR,
        'hub_to_first_minutes': None,
        'median_leg_minutes': None,
        'return_minutes': 0,
        'zone_based': False,
        # Định mức cụm đo từ chuyến thật nên MỖI CHẶNG đã gồm cả bốc dỡ và ký nhận tại
        # điểm. Cộng thêm `minutes_per_stop` nữa là tính hai lần: chuyến Nhơn Trạch 8 điểm
        # đo được 134 phút, cộng đúp thành 211 — đủ để kết luận sai là chuyến không kịp
        # buổi sáng rồi cắt bớt điểm.
        'service_in_leg': False,
    }
    if zone:
        params.update({
            'hub_to_first_minutes': zone.get('hub_to_first_minutes') or None,
            'median_leg_minutes': zone.get('median_leg_minutes') or None,
            'return_minutes': zone.get('return_minutes') or 0,
            'zone_based': True,
            'service_in_leg': True,
        })
    return params


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

    Với định mức cụm, mốc đo là lúc **GIAO XONG** (định mức lấy từ ``date_done`` của phiếu),
    nên ``depart`` bằng ``arrive``: thời gian đứng tại điểm đã nằm trong chặng kế tiếp.
    Với cách tính từ km thì ``arrive`` là lúc tới nơi, và ``depart`` = ``arrive`` +
    ``minutes_per_stop``.

    ``leg_km`` là None với điểm thiếu toạ độ. Điểm kế tiếp được đo từ điểm GẦN NHẤT CÓ
    TOẠ ĐỘ trước nó (nối thẳng qua điểm thiếu): theo bất đẳng thức tam giác đó là cận dưới
    chặt nhất có thể có, và khớp với cách ``total_path_km`` của hlv_geo_utils bỏ qua điểm
    lỗi. Vì vậy khi có điểm thiếu toạ độ, mọi con số ở đây là CẬN DƯỚI.

    Với định mức theo cụm, ``leg_minutes`` KHÔNG phụ thuộc quãng đường: chặng đầu lấy
    ``hub_to_first_minutes``, các chặng sau lấy ``median_leg_minutes``. Điểm thiếu toạ độ
    vẫn được tính thời gian chạy — xe vẫn phải đi tới đó, chỉ là mình không đo được bao xa.
    """
    legs = []
    previous = start
    clock = 0
    for index, stop in enumerate(stops):
        leg_km = _leg_distance(previous, stop, params)
        leg_minutes = _leg_minutes(leg_km, index, previous, params)
        clock += leg_minutes or 0
        arrive = clock
        clock += 0 if params['service_in_leg'] else params['minutes_per_stop']
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


def _leg_distance(previous, stop, params):
    """Quãng đường một chặng (km), hoặc None khi không đo được."""
    if not (stop and previous):
        return None
    straight = haversine_km(previous, stop)
    return None if straight is None else round(straight * params['road_factor'], 1)


def _leg_minutes(leg_km, index, previous, params):
    """Thời gian chạy một chặng.

    Chặng ĐẦU (index 0, có điểm xuất phát) khác hẳn các chặng sau: nó gồm cả quãng ra khỏi
    kho và thời gian xếp nốt hàng lên xe, nên luôn dài hơn — đo được 40–57 phút tuỳ cụm
    trong khi chặng trong cụm chỉ 13–15 phút.
    """
    if params['zone_based']:
        is_first_leg = index == 0 and previous is not None
        if is_first_leg and params['hub_to_first_minutes']:
            return params['hub_to_first_minutes']
        if not is_first_leg and params['median_leg_minutes']:
            # Chặng đầu khi KHÔNG có điểm xuất phát thì không có chặng nào để đi.
            return params['median_leg_minutes'] if index else None
        return None
    if leg_km is None:
        return None
    return int(round(leg_km / params['speed_kmh'] * 60))


def estimate_route(start, stops, params):
    """Tổng hợp cả lộ trình.

    Tham số như ``estimate_legs``. Trả về dict::

        {'distance_km', 'drive_minutes', 'service_minutes', 'return_minutes',
         'total_minutes', 'missing_coords_count', 'legs'}

    ``total_minutes`` gồm cả chặng VỀ KHO khi cụm có khai ``return_minutes``: một chuyến
    chỉ xong khi xe về tới kho, và với cụm xa thì chặng về đáng kể (Châu Đức 80 phút).

    Lộ trình rỗng trả về toàn số 0 và ``legs`` rỗng.
    """
    legs = estimate_legs(start, stops, params)
    distance = round(sum(leg['leg_km'] or 0.0 for leg in legs), 1)
    drive = sum(leg['leg_minutes'] or 0 for leg in legs)
    # Định mức cụm: thời gian tại điểm đã nằm trong từng chặng, không cộng lần nữa.
    # Tính từ km: km ÷ tốc độ chỉ ra thời gian CHẠY thuần, phải cộng thời gian đứng.
    service = 0 if params['service_in_leg'] else params['minutes_per_stop'] * len(stops)
    back = params['return_minutes'] if stops else 0
    return {
        'distance_km': distance,
        'drive_minutes': drive,
        'service_minutes': service,
        'return_minutes': back,
        'total_minutes': drive + service + back,
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
