"""Luật xếp chuyến — hàm thuần, vào gì ra nấy.

Không đụng ``self.env``. Nhận vào số và toạ độ, trả về kết luận. Tách khỏi model để test
được bằng python trần: đây là chỗ dễ sai nhất mà lại khó phát hiện — một chuyến xếp sai
chỉ lộ ra khi xe đã ra đường.
"""

from odoo.addons.hlv_geo_utils.tools.geo_distance import haversine_km


def zone_warnings(zone, stop_count, other_zone_names=()):
    """Cảnh báo về số điểm và việc gom nhiều cụm. Trả về list câu, rỗng nếu không có gì.

    zone: dict định mức cụm (``hlv.vtracking.zone.route_params()``), hoặc None.
    stop_count: số ĐIỂM DỪNG của kế hoạch — nhiều phiếu cùng một chỗ tính là một. Truyền
        số phiếu vào đây là báo vượt trần sai: trần của cụm đo bằng điểm.
    other_zone_names: tên các cụm KHÁC cũng có mặt trong kế hoạch.

    Trần điểm là trần **mềm** — chỉ cảnh báo, không chặn: điều phối biết rõ hơn hệ thống
    khi nào nên xếp thêm. Ngưỡng dưới thì đáng nói ngược lại: 65 trong 332 chuyến đo được
    chỉ có đúng một điểm, mỗi chuyến như vậy tốn cả chặng kho → cụm cho một lần giao.
    """
    messages = []
    if zone and stop_count:
        max_stops = zone.get('max_stops') or 0
        minimum = zone.get('min_stops_worth_trip') or 0
        name = zone.get('name') or 'cụm đang chọn'
        if max_stops and stop_count > max_stops:
            messages.append(
                'Vượt trần %s điểm của cụm %s (đang %s điểm).' % (max_stops, name, stop_count)
            )
        if minimum and stop_count < minimum:
            messages.append(
                'Chỉ %s điểm — dưới ngưỡng %s của cụm %s. Cân nhắc gộp sang chuyến khác '
                'hoặc gửi chuyển phát nhanh.' % (stop_count, minimum, name)
            )
    others = sorted(set(other_zone_names))
    if others:
        messages.append(
            'Gom nhiều cụm: %s. Mỗi điểm tính theo định mức cụm của nó; chặng nối giữa '
            'hai cụm chưa có số đo nên ước theo km. Trần điểm đang so theo cụm %s.'
            % (', '.join(others), (zone or {}).get('name') or 'chính')
        )
    return messages


# Cách điểm mẫu gần nhất dưới ngưỡng này thì tin được. Đo trên 86 ghim bản đồ bằng kiểu
# leave-one-out: ngưỡng 3 km cho 100% đúng trên 47/55 điểm dám tự gán; nới lên 5 km thì tự
# gán được 52 điểm nhưng tụt xuống 96%. Gán sai cụm nghĩa là xe chạy nhầm tuyến, còn hỏi
# người thì chỉ mất một cú click — nên chọn chặt.
DEFAULT_ZONE_MATCH_KM = 3.0


def nearest_zone(coords, samples, near_km=DEFAULT_ZONE_MATCH_KM):
    """Suy cụm tuyến từ TOẠ ĐỘ, bằng điểm mẫu đã biết gần nhất.

    coords: tuple ``(lat, lng)`` của điểm cần suy, hoặc None.
    samples: list tuple ``(zone_key, (lat, lng))`` — các điểm đã biết chắc thuộc cụm nào.
    near_km: dưới ngưỡng này thì coi là chắc chắn.

    Trả về ``(zone_key, distance_km, confident)``; ``(None, None, False)`` khi không có
    toạ độ hoặc chưa có điểm mẫu nào.

    Vì sao suy từ toạ độ chứ không từ khách hàng: một khách có thể có hai nơi giao thuộc
    hai cụm khác nhau (nhà máy và kho). Hỏi "khách này thuộc cụm nào" thì hai địa chỉ ra
    cùng một đáp án và một trong hai sẽ sai. Hỏi "toạ độ này gần cụm nào" thì đúng cả hai.

    Không dùng tâm cụm + bán kính: cụm Long Thành trải dài 21 km và Mỹ Xuân 29 km, vẽ
    vòng tròn quanh tâm chúng sẽ trùm lên cả cụm khác.
    """
    if not coords or not coords[0] or not coords[1] or not samples:
        return None, None, False
    best_key, best_distance = None, None
    for zone_key, sample in samples:
        if not sample or not sample[0] or not sample[1]:
            continue
        distance = haversine_km(coords, sample)
        if distance is None:
            continue
        if best_distance is None or distance < best_distance:
            best_key, best_distance = zone_key, distance
    if best_key is None:
        return None, None, False
    return best_key, round(best_distance, 2), best_distance <= near_km


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


# Thời gian đứng tại một điểm, đo trên chính kho này, theo SỐ PHIẾU giao tại điểm đó.
# Không theo khách: cùng cụm Nhơn Trạch, buổi sáng (1-7 phiếu/điểm) trung vị 13 phút, buổi
# chiều (đúng 1 phiếu/điểm) trung vị 3 phút — khác biệt nằm ở số phiếu phải ký và dỡ, không
# nằm ở khách. Gán theo khách là cách đã phải bỏ.
SERVICE_BY_PICKINGS = ((1, 4), (3, 15), (4, 22))
SERVICE_MANY_PICKINGS = 30


def service_minutes(picking_count):
    """Số phút đứng tại một điểm có ``picking_count`` phiếu. Hàm thuần.

    1 phiếu 4' · 2-3 phiếu 15' · 4 phiếu 22' · từ 5 phiếu 30'. Số phiếu <= 0 coi như 1 —
    điểm nào cũng phải dừng.
    """
    count = max(int(picking_count or 1), 1)
    for limit, minutes in SERVICE_BY_PICKINGS:
        if count <= limit:
            return minutes
    return SERVICE_MANY_PICKINGS


def extra_service_minutes(picking_count):
    """Phần đứng LÂU HƠN một điểm một-phiếu, để cộng vào ``extra_minutes`` của lộ trình.

    Định mức cụm đã bao thời gian đứng của một điểm bình thường (một phiếu), nên chỉ phần
    dôi ra mới được cộng — cộng cả ``service_minutes`` là tính hai lần.
    """
    return max(service_minutes(picking_count) - service_minutes(1), 0)
