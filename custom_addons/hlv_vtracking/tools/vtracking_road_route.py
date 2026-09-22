"""Dựng yêu cầu lộ trình ĐƯỜNG THẬT cho Google Routes API — hàm thuần, vào gì ra nấy.

Không đụng ``self.env``, không gọi mạng. Phần gọi HTTP nằm ở ``services/google_routes.py``:
tách ra để chỗ khó nhất (dựng body đúng cấu trúc, đọc số trả về, quyết định khi nào phải
gọi lại) kiểm chứng được bằng test mà không cần khoá API hay mạng.

Quan hệ với ``tools/vtracking_route.py``: file đó ước lượng bằng ĐƯỜNG CHIM BAY × hệ số và
định mức cụm, luôn chạy được, là con số để SO CÁC PHƯƠNG ÁN. File này lấy quãng đường và
hình dạng đường ĐI THẬT từ Google, chỉ có khi gọi được API. Hai con số cùng tồn tại là có
chủ ý — km chim bay vẫn là thứ so được giữa mọi kế hoạch kể cả khi API hỏng hoặc chưa bật.

Phạm vi lộ trình: kho → các điểm theo đúng thứ tự ghé, KHÔNG gồm chặng về kho — giống hệt
``estimate_route()['distance_km']``, để hai con số km so được với nhau. Chặng về chỉ được
tính vào THỜI GIAN (``return_minutes``), xem docstring của estimate_route.
"""

ROUTES_URL = 'https://routes.googleapis.com/directions/v2:computeRoutes'

# Chỉ xin đúng 3 thứ cần dùng. Google tính tiền theo hạng field mask: xin thừa (VD toàn bộ
# steps từng đoạn rẽ) là nhảy sang hạng đắt hơn mà không dùng tới.
FIELD_MASK = 'routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline'

# Số điểm GIỮA tối đa trong một lời gọi. Google cho nhiều hơn, nhưng 23 là mức an toàn
# chung của cả Routes API v2 và Directions API cũ — chuyến thực tế 8-12 điểm nên ngưỡng này
# gần như không chạm tới, và chạm thì phải báo lỗi rõ chứ không được lặng lẽ cắt bớt điểm
# (cắt là vẽ ra lộ trình thiếu điểm mà người xem không biết).
MAX_INTERMEDIATES = 23


class RoadRouteInputError(ValueError):
    """Đầu vào không gọi API được (quá ít điểm, quá nhiều điểm). Không phải lỗi mạng."""


def route_points(start, stops):
    """Danh sách toạ độ để gọi API: kho trước, rồi các điểm theo thứ tự ghé.

    ``start``: tuple (lat, lng) hoặc None. ``stops``: list các tuple (lat, lng) hoặc None
    cho điểm chưa tra được toạ độ — điểm None bị BỎ QUA, đúng như cách tính chim bay bỏ
    qua chúng (xem missing_coords_count).

    Trả về list tuple (lat, lng). Không có điểm nào thì trả list rỗng.
    """
    points = []
    if start:
        points.append((start[0], start[1]))
    for stop in stops or []:
        if stop:
            points.append((stop[0], stop[1]))
    return points


def route_signature(points):
    """Chuỗi nhận diện một lộ trình, để biết khi nào phải gọi lại API.

    Đổi thứ tự ghé, thêm/bớt điểm, hay đổi toạ độ một điểm đều ra chuỗi khác -> phải gọi
    lại. Giữ nguyên thì dùng bản đã lưu, không tốn thêm một lượt gọi.

    Làm tròn 5 chữ số thập phân (~1 m): toạ độ cùng một điểm có thể lệch ở chữ số cuối sau
    một lần tra lại, mà lệch 1 m thì đường đi không khác gì — không đáng gọi lại API.
    """
    return '|'.join('%.5f,%.5f' % (lat, lng) for lat, lng in points)


def _waypoint(point):
    return {'location': {'latLng': {'latitude': point[0], 'longitude': point[1]}}}


def compute_routes_body(points):
    """Body JSON cho computeRoutes từ danh sách toạ độ đã có thứ tự.

    Raise ``RoadRouteInputError`` nếu dưới 2 điểm (không có đoạn nào để đi) hoặc quá
    ``MAX_INTERMEDIATES`` điểm giữa.
    """
    if len(points) < 2:
        raise RoadRouteInputError(
            'Lộ trình cần ít nhất 2 điểm có toạ độ (kho và một điểm giao).'
        )
    intermediates = points[1:-1]
    if len(intermediates) > MAX_INTERMEDIATES:
        raise RoadRouteInputError(
            'Chuyến có %d điểm giữa, vượt mức %d điểm mỗi lượt gọi Google Routes. '
            'Tách chuyến hoặc bỏ bớt điểm.' % (len(intermediates), MAX_INTERMEDIATES)
        )
    return {
        'origin': _waypoint(points[0]),
        'destination': _waypoint(points[-1]),
        'intermediates': [_waypoint(point) for point in intermediates],
        'travelMode': 'DRIVE',
        # TRAFFIC_UNAWARE chứ không phải TRAFFIC_AWARE: đây là số dùng để LẬP KẾ HOẠCH và
        # được lưu lại: km/phút phải ổn định để hai người mở cùng một chuyến thấy cùng con
        # số, và để so được với kế hoạch hôm qua. Bản có traffic đổi theo từng phút và đắt
        # hơn — muốn giờ sát thực tế thì đã có định mức cụm đo từ chuyến thật, tốt hơn.
        'routingPreference': 'TRAFFIC_UNAWARE',
        # Giữ NGUYÊN thứ tự ghé do người điều phối/AI đã xếp. Thứ tự đó cân theo cụm tuyến,
        # thủ tục và thói quen khách — để Google xếp lại theo mỗi km ngắn nhất là phá bỏ
        # toàn bộ phần lý giải đó.
        'optimizeWaypointOrder': False,
        'polylineQuality': 'OVERVIEW',
        'languageCode': 'vi',
        'regionCode': 'VN',
        'units': 'METRIC',
    }


def parse_duration_seconds(value):
    """'1234s' -> 1234. Trả 0 nếu rỗng/không đọc được.

    Google trả thời lượng dạng chuỗi có hậu tố 's' (protobuf Duration), không phải số.
    """
    text = str(value or '').strip().rstrip('s')
    try:
        return int(float(text))
    except ValueError:
        return 0


def parse_route_response(payload):
    """Body JSON của computeRoutes -> dict ``{'distance_km', 'duration_minutes', 'polyline'}``.

    Trả None nếu Google không tìm được đường nào (mảng ``routes`` rỗng) — đây là kết quả
    hợp lệ của API chứ không phải lỗi, VD điểm giao bị geocode ra giữa ruộng không có
    đường xe vào.
    """
    routes = (payload or {}).get('routes') or []
    if not routes:
        return None
    route = routes[0]
    meters = route.get('distanceMeters') or 0
    seconds = parse_duration_seconds(route.get('duration'))
    return {
        'distance_km': round(meters / 1000.0, 1),
        'duration_minutes': int(round(seconds / 60.0)),
        'polyline': ((route.get('polyline') or {}).get('encodedPolyline') or ''),
    }
