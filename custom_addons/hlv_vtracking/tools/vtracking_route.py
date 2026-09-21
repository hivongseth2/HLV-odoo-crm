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

# Hai dòng liền nhau cách nhau dưới ngưỡng này coi là CÙNG MỘT ĐIỂM DỪNG. 50 m đủ rộng để
# nuốt sai số geocode giữa hai cách viết cùng một địa chỉ, đủ hẹp để hai nhà máy cạnh nhau
# trong KCN vẫn là hai điểm.
SAME_POINT_KM = 0.05


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
            'zone_id': zone.get('zone_id'),
            'zone_based': True,
            'service_in_leg': True,
        })
    return params


def _zone_from_params(params):
    """Định mức cụm nằm sẵn trong ``params`` (khi gọi ``route_params(zone=...)``), hoặc
    None. Dùng làm cụm mặc định cho điểm không được chỉ định cụm riêng."""
    if not params.get('zone_based'):
        return None
    return {
        'zone_id': params.get('zone_id'),
        'hub_to_first_minutes': params.get('hub_to_first_minutes'),
        'median_leg_minutes': params.get('median_leg_minutes'),
        'return_minutes': params.get('return_minutes') or 0,
    }


def _stop_zones(stop_zones, count, params):
    """Cụm của từng điểm, dài đúng ``count``. Không truyền thì mọi điểm dùng cụm trong
    ``params`` — giữ nguyên cách tính cũ cho bên gọi chưa biết tới cụm từng điểm."""
    default = _zone_from_params(params)
    zones = list(stop_zones or [])[:count]
    zones += [default] * (count - len(zones))
    return [zone or default for zone in zones]


def same_point(stop_a, stop_b, key_a=None, key_b=None):
    """Hai điểm có phải cùng MỘT điểm dừng không. Hàm thuần.

    Có toạ độ cả hai -> so khoảng cách với ``SAME_POINT_KM``. Thiếu toạ độ -> so khoá
    (thường là địa chỉ đã chuẩn hoá); khoá rỗng thì coi là khác nhau cho an toàn.

    Không so theo khách hàng: một khách có thể có hai nhà máy ở hai nơi.
    """
    if stop_a and stop_b:
        distance = haversine_km(stop_a, stop_b)
        return distance is not None and distance < SAME_POINT_KM
    return bool(key_a) and key_a == key_b


def _same_zone(zone_a, zone_b):
    return bool(zone_a and zone_b) and zone_a.get('zone_id') == zone_b.get('zone_id')


def estimate_legs(start, stops, params, extra_minutes=None, stop_zones=None, stop_keys=None):
    """Từng chặng của lộ trình, kèm giờ tới cộng dồn.

    start: tuple ``(lat, lng)`` điểm xuất phát, hoặc None.
    stops: list tuple ``(lat, lng)`` theo đúng thứ tự ghé; phần tử None = điểm CHƯA có toạ
        độ. Điểm thiếu toạ độ vẫn tính thời gian giao (xe vẫn phải ghé) nhưng không có
        quãng đường riêng.
    params: kết quả của ``route_params``.
    extra_minutes: list song song với ``stops``, số phút điểm đó đứng LÂU HƠN điểm thường
        (cổng xa, chờ cân, qua nhiều lớp bảo vệ). Thiếu phần tử thì phần thiếu coi như 0.
        Phút lâu hơn không làm trễ giờ TỚI chính điểm đó, nhưng làm trễ mọi điểm sau nó.

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

    stop_zones: list song song với ``stops`` — định mức cụm CỦA TỪNG ĐIỂM (dict như
        ``hlv.vtracking.zone.route_params()``, có ``zone_id``), hoặc None cho điểm chưa có
        cụm. Không truyền thì mọi điểm dùng cụm trong ``params``. Chuyến gom hai cụm cần
        tham số này: chặng trong Long Thành phải tính theo nhịp Long Thành, không phải theo
        cụm chiếm đa số của cả chuyến. Chặng VƯỢT CỤM không có số đo nào, nên tính theo
        km ÷ tốc độ cộng thời gian đứng tại điểm.
    stop_keys: list song song với ``stops`` — khoá nhận diện điểm khi thiếu toạ độ (thường
        là địa chỉ đã chuẩn hoá). Xem ``same_point``.

    **Nhiều đơn liền nhau tại cùng một điểm** (``same_point``) chỉ tính MỘT lần: chặng sau
    0 km, 0 phút, không cộng thời gian đứng hay phút lâu-hơn-thường-lệ lần nữa. Đơn vị tải
    của chuyến là ĐIỂM — đo được nhiều đơn cùng khách tốn thêm ~0 phút. Mỗi phần tử trả về
    có thêm ``same_point: bool``.
    """
    extras = _padded_extras(extra_minutes, len(stops))
    zones = _stop_zones(stop_zones, len(stops), params)
    keys = list(stop_keys or [])[:len(stops)]
    keys += [None] * (len(stops) - len(keys))

    legs = []
    previous = start
    clock = 0
    for index, stop in enumerate(stops):
        repeat = index > 0 and same_point(stops[index - 1], stop, keys[index - 1], keys[index])
        if repeat:
            leg_km, leg_minutes, service = 0.0, 0, 0
        else:
            leg_km = _leg_distance(previous, stop, params)
            prior_zone = zones[index - 1] if index else None
            leg_minutes = _leg_minutes(
                leg_km, index, start is not None, prior_zone, zones[index], params,
            )
            # Điểm có cụm: thời gian đứng đã nằm trong chặng. Điểm chưa có cụm: km ÷ tốc
            # độ chỉ ra thời gian chạy thuần, phải cộng thời gian đứng.
            service = (0 if zones[index] else params['minutes_per_stop']) + extras[index]
        clock += leg_minutes or 0
        arrive = clock
        clock += service
        legs.append({
            'leg_km': leg_km,
            'leg_minutes': leg_minutes,
            'arrive_offset_minutes': arrive,
            'depart_offset_minutes': clock,
            'same_point': repeat,
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


def _km_minutes(leg_km, params):
    """Thời gian chạy thuần suy từ quãng đường, hoặc None khi không đo được quãng đường."""
    if leg_km is None:
        return None
    return int(round(leg_km / params['speed_kmh'] * 60))


def _leg_minutes(leg_km, index, has_start, prior_zone, zone, params):
    """Thời gian một chặng — tới điểm thứ ``index``.

    Chặng ĐẦU (có điểm xuất phát) khác hẳn các chặng sau: nó gồm cả quãng ra khỏi kho và
    thời gian xếp nốt hàng lên xe, nên luôn dài hơn — đo được 40–57 phút tuỳ cụm trong khi
    chặng trong cụm chỉ 13–15 phút. Không có điểm xuất phát thì không có chặng đầu.

    Chặng trong CÙNG một cụm lấy ``median_leg_minutes`` của cụm đó. Chặng VƯỢT cụm (hoặc
    đi vào cụm từ một điểm chưa có cụm) không có số đo, nên lấy km ÷ tốc độ cộng thời gian
    đứng — cộng vào chính chặng, vì với điểm có cụm thời gian đứng nằm trong chặng. Không
    đo được km thì lùi về ``median_leg_minutes`` của cụm đích (cận dưới).
    """
    if index == 0:
        if not has_start:
            return None
        if zone and zone.get('hub_to_first_minutes'):
            return zone['hub_to_first_minutes']
        drive = _km_minutes(leg_km, params)
        if drive is not None and zone:
            drive += params['minutes_per_stop']
        return drive
    if zone and _same_zone(prior_zone, zone) and zone.get('median_leg_minutes'):
        return zone['median_leg_minutes']
    drive = _km_minutes(leg_km, params)
    if zone:
        if drive is None:
            return zone.get('median_leg_minutes')
        return drive + params['minutes_per_stop']
    return drive


def estimate_route(start, stops, params, extra_minutes=None, stop_zones=None, stop_keys=None):
    """Tổng hợp cả lộ trình.

    Tham số như ``estimate_legs``. Trả về dict::

        {'distance_km', 'drive_minutes', 'service_minutes', 'return_minutes',
         'total_minutes', 'missing_coords_count', 'legs'}

    ``service_minutes`` gồm cả phút lâu hơn thường lệ của từng điểm (xem ``extra_minutes``
    ở ``estimate_legs``).

    ``total_minutes`` gồm cả chặng VỀ KHO khi cụm có khai ``return_minutes``: một chuyến
    chỉ xong khi xe về tới kho, và với cụm xa thì chặng về đáng kể (Châu Đức 80 phút).
    Chặng về lấy theo cụm của ĐIỂM CUỐI — xe về từ đó, không phải từ cụm đa số.

    Lộ trình rỗng trả về toàn số 0 và ``legs`` rỗng.
    """
    extras = _padded_extras(extra_minutes, len(stops))
    legs = estimate_legs(start, stops, params, extras, stop_zones, stop_keys)
    distance = round(sum(leg['leg_km'] or 0.0 for leg in legs), 1)
    drive = sum(leg['leg_minutes'] or 0 for leg in legs)
    # Thời gian đứng = phần chênh giữa lúc rời và lúc tới của từng điểm. estimate_legs đã
    # quyết định điểm nào phải cộng (điểm chưa có cụm, phút lâu hơn thường lệ) và điểm nào
    # không (điểm có cụm — đã nằm trong chặng; đơn lặp tại cùng điểm) — cộng lại ở đây
    # theo luật riêng là hai chỗ giữ cùng một quy tắc.
    service = sum(leg['depart_offset_minutes'] - leg['arrive_offset_minutes'] for leg in legs)
    back = 0
    if stops:
        last_zone = _stop_zones(stop_zones, len(stops), params)[-1]
        back = (last_zone or {}).get('return_minutes') or params['return_minutes']
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


def _padded_extras(extra_minutes, count):
    """List phút-lâu-hơn dài đúng ``count``, phần thiếu điền 0, giá trị âm coi như 0.

    Gọi bên ngoài không cần biết có bao nhiêu điểm: thiếu thì bù, thừa thì cắt. Âm bị chặn
    vì "giao nhanh hơn thường lệ" không rút ngắn được chặng — chặng đã là số đo thực tế.
    """
    extras = [max(int(value or 0), 0) for value in (extra_minutes or [])][:count]
    return extras + [0] * (count - len(extras))
