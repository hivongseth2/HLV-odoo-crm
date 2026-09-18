"""Luật xếp chuyến — hàm thuần, vào gì ra nấy.

Không đụng ``self.env``. Nhận vào số và toạ độ, trả về kết luận. Tách khỏi model để test
được bằng python trần: đây là chỗ dễ sai nhất mà lại khó phát hiện — một chuyến xếp sai
chỉ lộ ra khi xe đã ra đường.
"""

from odoo.addons.hlv_geo_utils.tools.geo_distance import haversine_km


def zone_warnings(zone, line_count, other_zone_names=()):
    """Cảnh báo về số điểm và việc gom nhiều cụm. Trả về list câu, rỗng nếu không có gì.

    zone: dict định mức cụm (``hlv.vtracking.zone.route_params()``), hoặc None.
    line_count: số điểm đang có trong kế hoạch.
    other_zone_names: tên các cụm KHÁC cũng có mặt trong kế hoạch.

    Trần điểm là trần **mềm** — chỉ cảnh báo, không chặn: điều phối biết rõ hơn hệ thống
    khi nào nên xếp thêm. Ngưỡng dưới thì đáng nói ngược lại: 65 trong 332 chuyến đo được
    chỉ có đúng một điểm, mỗi chuyến như vậy tốn cả chặng kho → cụm cho một lần giao.
    """
    messages = []
    if zone and line_count:
        max_stops = zone.get('max_stops') or 0
        minimum = zone.get('min_stops_worth_trip') or 0
        name = zone.get('name') or 'cụm đang chọn'
        if max_stops and line_count > max_stops:
            messages.append(
                'Vượt trần %s điểm của cụm %s (đang %s điểm).' % (max_stops, name, line_count)
            )
        if minimum and line_count < minimum:
            messages.append(
                'Chỉ %s điểm — dưới ngưỡng %s của cụm %s. Cân nhắc gộp sang chuyến khác '
                'hoặc gửi chuyển phát nhanh.' % (line_count, minimum, name)
            )
    others = sorted(set(other_zone_names))
    if others:
        messages.append(
            'Gom nhiều cụm: %s. Định mức đang tính theo %s.'
            % (', '.join(others), (zone or {}).get('name') or 'cụm chính')
        )
    return messages


def nearest_first_order(start, points):
    """Thứ tự ghé theo kiểu "đi tới điểm gần nhất chưa ghé".

    start: tuple ``(lat, lng)`` điểm xuất phát, hoặc None.
    points: list tuple ``(key, coords)`` — ``coords`` là ``(lat, lng)`` hoặc None.

    Trả về list ``key`` theo thứ tự đề xuất. Điểm KHÔNG có toạ độ dồn xuống cuối, giữ
    nguyên thứ tự tương đối: không biết nó ở đâu thì không xếp vào giữa tuyến được, để
    cuối cho người điều phối tự quyết.

    Đây không phải lời giải tối ưu cho bài toán người giao hàng — chỉ là điểm khởi đầu đỡ
    tệ hơn thứ tự nhập tay. Không có điểm xuất phát thì lấy điểm đầu danh sách làm mốc.
    """
    located = [(key, coords) for key, coords in points if coords]
    unlocated = [key for key, coords in points if not coords]
    if not located:
        return unlocated

    ordered = []
    remaining = list(located)
    if start:
        current = start
    else:
        key, current = remaining.pop(0)
        ordered.append(key)

    while remaining:
        key, coords = min(
            remaining,
            key=lambda item: haversine_km(current, item[1]) or float('inf'),
        )
        ordered.append(key)
        current = coords
        remaining = [item for item in remaining if item[0] != key]
    return ordered + unlocated
