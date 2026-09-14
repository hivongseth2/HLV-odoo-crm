"""Công thức thời gian của chuyến đi nhận hàng — hàm thuần, không đụng ``self.env``.

Đây là NƠI DUY NHẤT định nghĩa "di chuyển mất bao lâu" và "nhận hàng mất bao lâu".
Model chỉ gọi vào đây rồi ghi kết quả; không có field nào cho người dùng gõ tay số phút.

Bốn mốc, tất cả đều do người đi nhận bấm:

    run.depart_at       → xuất phát
    stop.arrived_at     → tới cổng nhà cung cấp
    stop.done_at        → nhận xong, rời đi
    run.returned_at     → về kho (tuỳ chọn)

Hai quy tắc quan trọng, sai là ra số vô nghĩa:

1. **Tính theo thứ tự ĐI THỰC TẾ, không theo thứ tự kế hoạch.** Người đi nhận đảo điểm là
   chuyện thường (tắc đường, nhà cung cấp hẹn giờ khác). Lấy hiệu thời gian theo thứ tự kế
   hoạch sẽ ra số phút âm.
2. **Điểm chưa tới không cắt chuỗi.** Mốc gốc để tính di chuyển là điểm ĐÃ TỚI gần nhất
   trước đó; điểm bị bỏ qua giữa chừng bị nhảy qua chứ không làm hỏng cả chuyến.
"""

from datetime import datetime, timezone


def actual_order(stops):
    """Sắp các điểm theo thứ tự ĐI THỰC TẾ.

    stops: list dict, mỗi dict cần ``key``, ``sequence`` (int), ``arrived_at`` (datetime|None).
    Điểm đã tới xếp trước theo ``arrived_at`` tăng dần; điểm chưa tới xếp sau, giữ nguyên
    thứ tự kế hoạch. Danh sách rỗng trả về [].
    """
    visited = [s for s in stops if s.get('arrived_at')]
    pending = [s for s in stops if not s.get('arrived_at')]
    visited.sort(key=lambda s: (s['arrived_at'], s.get('sequence') or 0, str(s.get('key'))))
    pending.sort(key=lambda s: (s.get('sequence') or 0, str(s.get('key'))))
    return [s['key'] for s in visited + pending]


def compute_run_timings(depart_at, returned_at, stops):
    """Tính toàn bộ số phút của một chuyến.

    depart_at, returned_at: datetime|None.
    stops: list dict ``{'key', 'sequence', 'arrived_at', 'done_at'}`` — không cần sắp trước.

    Trả về dict::

        {
            'order': [key, ...],                       # thứ tự đi thực tế
            'stops': {key: {'travel_minutes': int|None,
                            'service_minutes': int|None,
                            'chain_broken': bool}},
            'total_travel_minutes': int,               # cộng các giá trị tính được
            'total_service_minutes': int,
            'total_minutes': int|None,                 # từ xuất phát tới mốc cuối
            'idle_minutes': int|None,                  # tổng trừ đi di chuyển và nhận hàng
        }

    ``travel_minutes`` là None khi không có mốc gốc hoặc khi hiệu ra số âm (bấm nhầm thứ
    tự) — kèm ``chain_broken=True`` để báo cáo loại dòng đó ra thay vì cộng bừa số 0.
    Chuyến chưa xuất phát / chưa có điểm nào: mọi tổng bằng 0, ``total_minutes`` là None.
    """
    by_key = {s['key']: s for s in stops}
    order = actual_order(stops)

    result = {}
    previous_ref = depart_at
    for key in order:
        stop = by_key[key]
        arrived = stop.get('arrived_at')
        done = stop.get('done_at')

        travel = minutes_between(previous_ref, arrived)
        chain_broken = bool(arrived) and travel is None
        result[key] = {
            'travel_minutes': travel,
            'service_minutes': minutes_between(arrived, done),
            'chain_broken': chain_broken,
        }
        # Mốc gốc cho điểm sau là lúc RỜI điểm này. Chưa bấm rời thì dùng lúc tới — còn
        # hơn là mất mốc và làm gãy chuỗi cho mọi điểm còn lại.
        if done or arrived:
            previous_ref = done or arrived

    total_travel = sum(v['travel_minutes'] or 0 for v in result.values())
    total_service = sum(v['service_minutes'] or 0 for v in result.values())
    total = minutes_between(depart_at, returned_at or previous_ref)

    return {
        'order': order,
        'stops': result,
        'total_travel_minutes': total_travel,
        'total_service_minutes': total_service,
        'total_minutes': total,
        'idle_minutes': None if total is None else max(total - total_travel - total_service, 0),
    }


def minutes_between(start, end):
    """Số phút từ ``start`` tới ``end``, làm tròn.

    Trả về None khi thiếu một trong hai mốc, hoặc khi ``end`` trước ``start`` — mốc ngược
    nghĩa là có người bấm nhầm, trả 0 sẽ giấu mất lỗi đó.
    """
    if not start or not end:
        return None
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return None
    return int(round(seconds / 60.0))


def parse_iso_datetime(value):
    """Đọc chuỗi ISO từ trình duyệt ("2026-09-14T08:12:33.000Z") thành datetime UTC không tzinfo.

    Odoo lưu datetime dạng UTC naive, nên phải bỏ tzinfo sau khi quy đổi. Chuỗi rỗng hoặc
    không đọc được trả về None — gọi hàm này xong luôn phải có đường lui.
    """
    if not value:
        return None
    text = str(value).strip().replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def pick_event_time(client_time, server_now, max_drift_minutes=720):
    """Chọn mốc nào đáng tin giữa giờ bấm trên điện thoại và giờ máy chủ nhận được.

    Ưu tiên giờ BẤM: điện thoại mất sóng rồi gửi lại sau 20 phút thì giờ máy chủ không còn
    là lúc người ta đứng ở nhà cung cấp nữa.

    Nhưng đồng hồ điện thoại cũng có thể sai hẳn (đặt sai ngày, sai múi giờ). Lệch quá
    ``max_drift_minutes`` thì bỏ, dùng giờ máy chủ: một mốc muộn 20 phút còn đọc được, một
    mốc lệch 3 ngày làm hỏng cả báo cáo.
    """
    if not client_time:
        return server_now
    drift = abs((client_time - server_now).total_seconds()) / 60.0
    return client_time if drift <= max_drift_minutes else server_now


def median(values):
    """Trung vị của list số. Bỏ qua None. Rỗng trả về None.

    Dùng trung vị chứ không dùng trung bình cho định mức thời gian: một lần chờ nhà cung
    cấp 3 tiếng sẽ kéo trung bình lên và làm mọi dự kiến sau đó sai.
    """
    clean = sorted(v for v in (values or []) if v is not None)
    if not clean:
        return None
    middle = len(clean) // 2
    if len(clean) % 2:
        return float(clean[middle])
    return (clean[middle - 1] + clean[middle]) / 2.0


def average(values):
    """Trung bình cộng, bỏ qua None. Rỗng trả về None."""
    clean = [v for v in (values or []) if v is not None]
    if not clean:
        return None
    return sum(clean) / float(len(clean))
