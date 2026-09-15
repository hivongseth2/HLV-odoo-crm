"""Gọi Google Maps: tra toạ độ, đo thời gian giữa các điểm, sắp thứ tự đi.

Đây là file DUY NHẤT trong module chạm mạng. Mọi thứ khác tính toán thuần để còn test được
mà không cần key.

Hai chuyện về tiền và bảo mật, quyết định cách viết file này:

1. **Mỗi lần bấm là một lượt tính tiền.** Vì vậy module chỉ dùng Directions (một lượt gọi
   trả về cả thứ tự lẫn thời gian từng chặng) chứ không dùng Distance Matrix vốn tính tiền
   theo từng phần tử của ma trận; số lần bấm bị chặn trần ở ``hlv.pickup.run``; và mọi điểm
   đều ưu tiên gửi ``place_id`` thay vì địa chỉ chữ — địa chỉ chữ bắt Google tra lại từ đầu.
2. **Có hai key, không được lẫn.** Key server (file này) không bao giờ được gửi xuống trình
   duyệt. Key JS nhúng trong trang ``/pickup`` thì chắc chắn lộ, nên nó phải được khoá theo
   HTTP referrer ở Google Cloud Console — đó là cách duy nhất bảo vệ nó.
"""

import logging

import requests

from odoo.exceptions import UserError

from .pickup_address import partner_address_text

_logger = logging.getLogger(__name__)

BASE_URL = 'https://maps.googleapis.com/maps/api'
TIMEOUT = 20
# Directions cho tối đa 25 điểm dừng mỗi lần gọi (gói thường). Quá số này thì không tối ưu
# được trong một lần — chuyến đi nhận hàng thực tế chưa bao giờ tới mức đó.
MAX_WAYPOINTS = 23

PARAM_SERVER_KEY = 'hlv_purchase_pickup.google_server_key'
PARAM_JS_KEY = 'hlv_purchase_pickup.google_js_key'

# Google trả status bằng chuỗi. Dịch sang câu người dùng hiểu được, vì lỗi hay gặp nhất
# (chưa bật billing, key sai) mà hiện nguyên "REQUEST_DENIED" thì không ai biết phải làm gì.
_STATUS_MESSAGE = {
    'REQUEST_DENIED': 'Google từ chối yêu cầu. Kiểm tra API key máy chủ và xem đã bật '
                      'thanh toán (billing) cho project chưa.',
    'OVER_QUERY_LIMIT': 'Đã vượt hạn mức Google Maps. Thử lại sau, hoặc nâng hạn mức trong '
                        'Google Cloud Console.',
    'INVALID_REQUEST': 'Yêu cầu gửi lên Google thiếu tham số — thường là do điểm chưa có '
                       'toạ độ lẫn địa chỉ.',
    'MAX_WAYPOINTS_EXCEEDED': 'Chuyến có quá nhiều điểm để Google sắp trong một lần. '
                              'Tách bớt điểm sang chuyến khác.',
    'UNKNOWN_ERROR': 'Google gặp lỗi tạm thời. Bấm lại sau ít giây.',
}


def server_key(env):
    """API key dùng ở máy chủ. Chuỗi rỗng nghĩa là chưa khai."""
    return (env['ir.config_parameter'].sudo().get_param(PARAM_SERVER_KEY) or '').strip()


def js_key(env):
    """API key nhúng vào trang /pickup. Chuỗi rỗng thì trang chạy không có bản đồ."""
    return (env['ir.config_parameter'].sudo().get_param(PARAM_JS_KEY) or '').strip()


def is_configured(env):
    return bool(server_key(env))


def geocode_address(env, address):
    """Tra toạ độ của một địa chỉ chữ.

    Trả về dict ``{'lat', 'lng', 'place_id', 'formatted'}``, hoặc None khi Google không tìm
    được kết quả nào. Lỗi cấu hình / hết quota thì raise UserError.
    """
    if not (address or '').strip():
        return None
    payload = _call(env, 'geocode/json', {'address': address, 'region': 'vn'})
    results = payload.get('results') or []
    if not results:
        return None
    best = results[0]
    location = (best.get('geometry') or {}).get('location') or {}
    if 'lat' not in location or 'lng' not in location:
        return None
    return {
        'lat': float(location['lat']),
        'lng': float(location['lng']),
        'place_id': best.get('place_id') or '',
        'formatted': best.get('formatted_address') or '',
    }


def route_legs(env, origin, waypoints, destination=None, optimize=True):
    """Hỏi Google đường đi qua các điểm: từng chặng hết bao lâu, và (tuỳ chọn) nên đi thứ tự nào.

    origin: nơi xuất phát. waypoints: list các điểm phải ghé. destination: nơi kết thúc;
    để trống thì quay về ``origin``.
    optimize=True: để Google sắp lại thứ tự cho ngắn nhất.
    optimize=False: giữ nguyên thứ tự đang có, chỉ lấy lại số liệu từng chặng — dùng khi
    quản lý đã tự sắp tay và chỉ muốn cập nhật giờ dự kiến.

    Trả về dict::

        {'order': [chỉ số waypoint theo thứ tự nên đi],
         'legs': [{'minutes', 'km'}, ...],   # legs[0] là chặng xuất phát → điểm đầu
         'total_minutes': int, 'total_km': float,
         'polyline': str}                    # đường đi đã nén, để vẽ lên bản đồ

    Danh sách waypoint rỗng trả về kết quả rỗng chứ không gọi Google.
    """
    if not waypoints:
        return {'order': [], 'legs': [], 'total_minutes': 0, 'total_km': 0.0, 'polyline': ''}
    if len(waypoints) > MAX_WAYPOINTS:
        raise UserError(
            'Chuyến có %d điểm, vượt mức %d điểm mà Google sắp được trong một lần. '
            'Tách bớt sang chuyến khác.' % (len(waypoints), MAX_WAYPOINTS)
        )

    params = {
        'origin': _place_param(origin),
        'destination': _place_param(destination or origin),
        'mode': 'driving',
    }
    prefix = 'optimize:true|' if optimize else ''
    params['waypoints'] = prefix + '|'.join(_place_param(p) for p in waypoints)

    payload = _call(env, 'directions/json', params)
    routes = payload.get('routes') or []
    if not routes:
        return {'order': list(range(len(waypoints))), 'legs': [], 'total_minutes': 0,
                'total_km': 0.0, 'polyline': ''}

    route = routes[0]
    order = route.get('waypoint_order') if optimize else list(range(len(waypoints)))
    if not isinstance(order, list) or len(order) != len(waypoints):
        # Google không sắp được (VD có điểm trùng nhau) — giữ nguyên thứ tự đang có còn hơn
        # là ném lỗi và mất luôn số liệu chặng vừa trả về.
        order = list(range(len(waypoints)))

    legs = [_leg_to_dict(leg) for leg in route.get('legs') or []]
    return {
        'order': order,
        'legs': legs,
        'total_minutes': sum(leg['minutes'] for leg in legs),
        'total_km': round(sum(leg['km'] for leg in legs), 1),
        # Đường đi thật theo đường bộ, dạng chuỗi nén của Google. Vẽ đường thẳng nối các
        # điểm thì trông như đi xuyên nhà dân, vô dụng với người đang cầm lái.
        'polyline': (route.get('overview_polyline') or {}).get('points') or '',
    }


def place_of_point(point):
    """Tham số địa điểm của một ``hlv.pickup.point``.

    Ưu tiên place_id (Google khỏi tra lại địa chỉ = khỏi tính thêm tiền), rồi tới toạ độ,
    cuối cùng mới tới địa chỉ chữ. Điểm không có gì cả trả về None.
    """
    if not point:
        return None
    if point.google_place_id:
        return {'place_id': point.google_place_id}
    if point.latitude and point.longitude:
        return {'lat': point.latitude, 'lng': point.longitude}
    if point.address:
        return {'address': point.address}
    return None


def place_of_partner(partner):
    """Tham số địa điểm của một liên hệ Odoo — dùng cho kho xuất phát.

    Toạ độ của ``base_geolocalize`` nếu có, không thì địa chỉ chữ. Trả None khi không có gì.
    """
    if not partner:
        return None
    if partner.partner_latitude and partner.partner_longitude:
        return {'lat': partner.partner_latitude, 'lng': partner.partner_longitude}
    address = partner_address_text(partner)
    return {'address': address} if address else None


# ----------------------------------------------------------------------
# Nội bộ
# ----------------------------------------------------------------------
def _place_param(place):
    """dict địa điểm -> chuỗi Google hiểu được."""
    if not place:
        raise UserError('Có điểm chưa khai toạ độ lẫn địa chỉ nên không tính đường được.')
    if place.get('place_id'):
        return 'place_id:%s' % place['place_id']
    if place.get('lat') is not None and place.get('lng') is not None:
        return '%s,%s' % (place['lat'], place['lng'])
    if place.get('address'):
        return place['address']
    raise UserError('Có điểm chưa khai toạ độ lẫn địa chỉ nên không tính đường được.')


def _leg_to_dict(leg):
    duration = (leg or {}).get('duration') or {}
    distance = (leg or {}).get('distance') or {}
    return {
        'minutes': int(round((duration.get('value') or 0) / 60.0)),
        'km': round((distance.get('value') or 0) / 1000.0, 1),
    }


def _call(env, endpoint, params):
    """Gọi một endpoint Google Maps, trả về payload đã parse.

    Ném UserError bằng tiếng Việt cho mọi lỗi có thể xảy ra — người bấm nút là người đi nhận
    hàng đang đứng ngoài đường, không phải lập trình viên đọc traceback.
    """
    key = server_key(env)
    if not key:
        raise UserError(
            'Chưa khai API key Google Maps (máy chủ). Vào Cấu hình → Đi nhận hàng để khai.'
        )
    try:
        response = requests.get(
            '%s/%s' % (BASE_URL, endpoint), params=dict(params, key=key), timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout:
        raise UserError('Google Maps không trả lời kịp. Kiểm tra mạng rồi bấm lại.')
    except requests.RequestException as error:
        _logger.warning('Lỗi gọi Google Maps %s: %s', endpoint, error)
        raise UserError('Không gọi được Google Maps. Kiểm tra kết nối mạng của máy chủ.')
    except ValueError:
        # requests ném JSONDecodeError, vốn là con của ValueError — bắt lớp cha là đủ.
        raise UserError('Google Maps trả về dữ liệu không đọc được.')

    status = payload.get('status')
    if status in ('OK', 'ZERO_RESULTS'):
        return payload
    message = _STATUS_MESSAGE.get(status, 'Google Maps báo lỗi: %s' % status)
    if payload.get('error_message'):
        _logger.warning('Google Maps %s: %s', status, payload['error_message'])
    raise UserError(message)
