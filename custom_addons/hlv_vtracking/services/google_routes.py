"""Gọi Google Routes API để lấy lộ trình đường thật.

Chỉ file này chạm mạng; cách dựng yêu cầu và đọc kết quả nằm ở
``tools/vtracking_road_route.py`` (hàm thuần, có test). Tách ra vì mọi lỗi ở đây là lỗi
NGOÀI tầm kiểm soát — hết quota, khoá bị chặn domain, mạng chậm — và phải được biến thành
một câu người điều phối đọc hiểu rồi lưu lại, chứ không được ném traceback lên màn hình
hoặc bị nuốt im lặng.
"""

import logging

import requests

from ..tools.vtracking_road_route import (
    FIELD_MASK,
    ROUTES_URL,
    RoadRouteInputError,
    compute_routes_body,
    parse_route_response,
)

_logger = logging.getLogger(__name__)

# 20 giây: Google thường trả trong dưới 1 giây, nhưng một chuyến 20 điểm lúc API chậm có
# thể lâu hơn. Không để mặc định vô hạn — người bấm nút sẽ ngồi chờ một trang treo.
TIMEOUT_SECONDS = 20


class RoadRouteError(Exception):
    """Không lấy được lộ trình. ``str(exc)`` là câu để hiện cho người dùng và lưu vào
    ``road_route_error`` — viết bằng tiếng người, nói rõ phải làm gì."""


def fetch_road_route(api_key, points):
    """Lộ trình đường thật qua các điểm đã có thứ tự.

    ``points``: list tuple (lat, lng), phần tử đầu là điểm xuất phát (xem
    ``tools.vtracking_road_route.route_points``).

    Trả về dict ``{'distance_km', 'duration_minutes', 'polyline'}``, hoặc None khi Google
    không tìm được đường nào đi qua hết các điểm (kết quả hợp lệ, không phải lỗi).

    Raise ``RoadRouteError`` cho mọi trường hợp không gọi được hoặc gọi mà bị từ chối.
    """
    if not api_key:
        raise RoadRouteError(
            'Chưa có khoá API Google. Vào Cấu hình V-Tracking, điền "Khoá API Google Maps" '
            'và bật Routes API cho khoá đó trong Google Cloud Console.'
        )
    try:
        body = compute_routes_body(points)
    except RoadRouteInputError as exc:
        # Lỗi đầu vào là lỗi của dữ liệu kế hoạch, không phải của Google — vẫn phải hiện ra
        # cho người dùng bằng cùng một đường, nhưng không gọi mạng vô ích.
        raise RoadRouteError(str(exc)) from exc

    try:
        response = requests.post(
            ROUTES_URL,
            json=body,
            headers={
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': api_key,
                'X-Goog-FieldMask': FIELD_MASK,
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise RoadRouteError(
            'Google không trả lời trong %d giây. Thử lại; nếu lặp lại nhiều lần thì kiểm '
            'tra đường ra Internet của server.' % TIMEOUT_SECONDS
        ) from exc
    except requests.RequestException as exc:
        raise RoadRouteError('Không gọi được Google Routes: %s' % exc) from exc

    if response.status_code != 200:
        raise RoadRouteError(_error_message(response))

    try:
        payload = response.json()
    except ValueError as exc:
        raise RoadRouteError('Google trả về dữ liệu không đọc được.') from exc

    return parse_route_response(payload)


def _error_message(response):
    """Lỗi HTTP của Google -> câu cho người dùng.

    Google gói lý do thật trong ``error.message`` (VD "Routes API has not been used in
    project ... before or it is disabled"). Hiện nguyên câu đó ra: đọc được ngay là thiếu
    bật API, sai khoá, hay hết quota — che lại thành "lỗi 403" là mất hẳn thông tin đó.
    """
    detail = ''
    try:
        detail = ((response.json() or {}).get('error') or {}).get('message') or ''
    except ValueError:
        detail = (response.text or '')[:300]
    _logger.warning('Google Routes trả về %s: %s', response.status_code, detail)
    if response.status_code in (401, 403):
        return ('Google từ chối khoá API (HTTP %s): %s — kiểm tra khoá đã bật Routes API '
                'và không bị giới hạn theo domain/IP.' % (response.status_code, detail))
    if response.status_code == 429:
        return 'Đã hết hạn mức gọi Google Routes (HTTP 429): %s' % detail
    return 'Google Routes lỗi HTTP %s: %s' % (response.status_code, detail)
