"""Đo khoảng cách giữa hai toạ độ — hàm thuần, không gọi mạng.

Đây là khoảng cách ĐƯỜNG CHIM BAY. Không dùng để hứa với người dùng là đi mất bao lâu:
việc đó phải hỏi Google Directions vì khu công nghiệp có đường một chiều và cổng riêng.
Chỗ dùng đúng của nó là: (1) so toạ độ GPS lúc bấm "đã tới" với toạ độ điểm để biết có
đứng đúng chỗ không, (2) sắp thứ tự gợi ý khi chưa có/không gọi được Google.
"""

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(point_a, point_b):
    """Khoảng cách đường chim bay giữa 2 điểm, đơn vị km.

    point_a, point_b: tuple (lat, lng) — chấp nhận số hoặc chuỗi số.
    Trả về float, hoặc None nếu một trong hai điểm thiếu/không hợp lệ.
    """
    first = _as_coords(point_a)
    second = _as_coords(point_b)
    if first is None or second is None:
        return None

    lat1, lng1 = math.radians(first[0]), math.radians(first[1])
    lat2, lng2 = math.radians(second[0]), math.radians(second[1])
    d_lat = lat2 - lat1
    d_lng = lng2 - lng1

    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def haversine_m(point_a, point_b):
    """Như ``haversine_km`` nhưng trả về mét (làm tròn), hoặc None."""
    km = haversine_km(point_a, point_b)
    return None if km is None else int(round(km * 1000))


def total_path_km(points):
    """Tổng chiều dài đường gấp khúc đi qua lần lượt các điểm.

    points: list tuple (lat, lng). Điểm không hợp lệ bị BỎ QUA (nối thẳng điểm trước với
    điểm sau) thay vì làm hỏng cả tổng — danh sách điểm thật luôn có vài điểm thiếu toạ độ.
    Danh sách dưới 2 điểm hợp lệ trả về 0.0.
    """
    valid = [c for c in (_as_coords(p) for p in (points or [])) if c is not None]
    if len(valid) < 2:
        return 0.0
    return sum(
        haversine_km(valid[i], valid[i + 1]) or 0.0
        for i in range(len(valid) - 1)
    )


def _as_coords(value):
    """(lat, lng) hợp lệ, hoặc None. Cả hai bằng 0 coi như chưa có toạ độ."""
    if not value:
        return None
    try:
        lat = float(value[0])
        lng = float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        return None
    if not lat and not lng:
        return None
    return lat, lng
