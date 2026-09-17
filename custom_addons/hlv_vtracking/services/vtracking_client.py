"""Lớp HTTP nói chuyện với vTracking Open API 1.0.3.

Chỉ biết HTTP, không biết Odoo: nhận cấu hình qua tham số khởi tạo, trả về dict thô của
API. Nhờ vậy gọi thử được từ shell mà không cần dựng env, và đổi cách lưu cấu hình sau
này không phải sửa file này.

Tài liệu chỉ có 2 endpoint:
    POST /api/v1/vtracking/vehicle/search        danh sách xe + vị trí hiện tại
    GET  /api/v1/vtracking/vehicle/journey/:id   lịch sử hành trình một xe
"""

import logging
import time
import warnings

import requests
from urllib3.exceptions import InsecureRequestWarning

_logger = logging.getLogger(__name__)

SEARCH_PATH = '/api/v1/vtracking/vehicle/search'
JOURNEY_PATH = '/api/v1/vtracking/vehicle/journey/%s'

# Trần của API theo tài liệu. Xin nhiều hơn cũng chỉ nhận được bấy nhiêu.
MAX_LIMIT = 500

# Trần số trang khi lấy hành trình. Một xe chạy cả ngày ~1000-1500 bản ghi, 20 trang là
# quá đủ; có trần để một ngày dữ liệu lỗi không treo cron vô hạn.
DEFAULT_MAX_PAGES = 20

# Nghỉ giữa hai request. Tài liệu không công bố hạn mức, chỉ có mã 429, nên đi chậm.
THROTTLE_SECONDS = 0.3

# Lùi dần khi gặp 429.
RETRY_DELAYS = (1, 2, 4, 8)

# Thuộc tính lấy mặc định. Không xin "air" vì điều hoà không nói gì về vận hành đội xe,
# và mỗi thuộc tính thừa là thêm dữ liệu phải tải cho mọi xe, mọi lượt đồng bộ.
DEFAULT_ATTRIBUTES = ('datas', 'status', 'acc', 'door', 'alarm', 'driverName')


class VTrackingError(Exception):
    """Gọi API thất bại. ``status_code`` là None khi lỗi xảy ra trước lúc có phản hồi."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class VTrackingClient:
    """Client cho một tài khoản vTracking.

    base_url: gốc host, ví dụ ``https://171.229.16.202:8443``.
    api_key: giá trị header ``APIKey``.
    verify_ssl: host là IP trần nên chứng chỉ nhiều khả năng tự ký. Mặc định vẫn kiểm
        tra; tắt là quyết định của người cấu hình và phải cố ý.
    """

    def __init__(self, base_url, api_key, verify_ssl=True, timeout=20):
        if not base_url or not api_key:
            raise VTrackingError('Chưa cấu hình địa chỉ máy chủ hoặc API key vTracking.')
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Endpoint 1: danh sách xe
    # ------------------------------------------------------------------
    def search_vehicles(self, plates=None, attributes=None, expand=False,
                        limit=MAX_LIMIT, offset=0):
        """Một trang danh sách xe. Trả về dict thô ``{total, offset, limit, vehicles}``.

        plates: list biển số cần lấy. Để None thì lấy toàn bộ xe của công ty.
        expand: True mới lấy được xe của công ty con.
        """
        params = {
            'limit': min(int(limit or MAX_LIMIT), MAX_LIMIT),
            'offset': int(offset or 0),
            'expand': 'true' if expand else 'false',
        }
        body = {'attributes': list(attributes or DEFAULT_ATTRIBUTES)}
        if plates:
            body['plates'] = list(plates)
        return self._request('POST', SEARCH_PATH, params=params, json_body=body)

    def iter_vehicles(self, plates=None, attributes=None, expand=False, max_pages=DEFAULT_MAX_PAGES):
        """Duyệt hết mọi trang xe, sinh ra từng phần tử ``vehicles[]``.

        Phân trang bằng offset. Dừng khi trang trả về rỗng hoặc đã lấy đủ ``total``.
        """
        offset = 0
        for _page in range(max_pages):
            payload = self.search_vehicles(
                plates=plates, attributes=attributes, expand=expand,
                limit=MAX_LIMIT, offset=offset,
            )
            vehicles = payload.get('vehicles') or []
            for vehicle in vehicles:
                yield vehicle
            offset += len(vehicles)
            total = payload.get('total')
            if not vehicles or (isinstance(total, int) and offset >= total):
                return
        _logger.warning(
            'vTracking: chạm trần %s trang khi lấy danh sách xe, có thể còn xe chưa lấy.',
            max_pages,
        )

    # ------------------------------------------------------------------
    # Endpoint 2: hành trình một xe
    # ------------------------------------------------------------------
    def get_journey(self, vtracking_id, start_ms=None, end_ms=None, limit=MAX_LIMIT, after=None):
        """Một trang hành trình. Trả về dict thô ``{before, after, additional_info, logs}``.

        vtracking_id là UUID lấy từ danh sách xe, không phải biển số.
        """
        params = {'limit': min(int(limit or MAX_LIMIT), MAX_LIMIT)}
        # Luôn truyền mốc thời gian tường minh: mặc định của API tính theo giờ máy chủ
        # vTracking, không phải giờ của mình.
        if start_ms is not None:
            params['startTime'] = int(start_ms)
        if end_ms is not None:
            params['endTime'] = int(end_ms)
        if after:
            params['after'] = after
        return self._request('GET', JOURNEY_PATH % vtracking_id, params=params)

    def iter_journey_pages(self, vtracking_id, start_ms=None, end_ms=None,
                           limit=MAX_LIMIT, max_pages=DEFAULT_MAX_PAGES):
        """Duyệt hết hành trình trong khoảng thời gian, sinh ra từng payload trang.

        Sinh cả payload chứ không chỉ ``logs`` vì ``additional_info.d`` (quãng đường)
        nằm ở cấp payload và phải cộng dồn qua từng trang.

        Con trỏ ``after`` chỉ là base64 của epoch mili-giây; cứ truyền lại nguyên chuỗi.
        ``after = None`` là hết dữ liệu.
        """
        after = None
        for _page in range(max_pages):
            payload = self.get_journey(
                vtracking_id, start_ms=start_ms, end_ms=end_ms, limit=limit, after=after,
            )
            yield payload
            after = payload.get('after')
            if not after:
                return
        _logger.warning(
            'vTracking: chạm trần %s trang hành trình của xe %s — dữ liệu bị cắt.',
            max_pages, vtracking_id,
        )

    # ------------------------------------------------------------------
    # Hạ tầng
    # ------------------------------------------------------------------
    def ping(self):
        """Gọi thử một request nhỏ nhất để kiểm tra cấu hình. Ném VTrackingError nếu hỏng."""
        payload = self.search_vehicles(limit=1, attributes=['status'])
        return {
            'total': payload.get('total', 0),
            'sample_plate': (payload.get('vehicles') or [{}])[0].get('license_plate', ''),
        }

    @staticmethod
    def _auth_error_message(response):
        """Câu giải thích cho 401/403 — phân biệt bị proxy chặn với bị ứng dụng từ chối.

        Đo được ngày 17/09/2026: gọi bằng key sai trả về HTML 403 của **nginx**, không
        phải JSON của ứng dụng. Khi cái chặn là proxy chứ không phải ứng dụng thì đổi key
        bao nhiêu lần cũng vô ích — thường là máy chủ Odoo chưa nằm trong whitelist IP.
        Phân biệt được hai trường hợp này giúp khỏi mất buổi đi dò nhầm phía.
        """
        body = (response.text or '').strip()
        blocked_by_proxy = 'nginx' in body.lower() or body.lower().startswith('<html')
        if blocked_by_proxy:
            return (
                'vTracking trả HTTP %s và phản hồi đến từ máy chủ proxy (nginx), không phải '
                'từ ứng dụng vTracking. Thường là địa chỉ IP của máy chủ Odoo chưa được '
                'vTracking cho vào danh sách cho phép. Hãy hỏi vTracking xem API key có bị '
                'khoá theo IP không, và báo cho họ IP public của máy chủ Odoo.'
                % response.status_code
            )
        return (
            'vTracking từ chối API key (HTTP %s). Kiểm tra lại giá trị đã dán vào ô "API key '
            'vTracking". Chi tiết: %s' % (response.status_code, body[:200])
        )

    def _request(self, method, path, params=None, json_body=None):
        """Gọi API, tự lùi dần khi gặp 429. Trả về dict đã giải JSON.

        Ném ``VTrackingError`` với ``status_code`` cho mọi trường hợp không dùng được:
        HTTP lỗi, thân phản hồi không phải JSON, hoặc JSON không phải object.
        """
        url = self.base_url + path
        headers = {'Content-Type': 'application/json', 'APIKey': self.api_key}
        last_error = None

        for attempt, delay in enumerate((0,) + RETRY_DELAYS):
            if delay:
                time.sleep(delay)
            elif attempt:
                time.sleep(THROTTLE_SECONDS)
            try:
                with warnings.catch_warnings():
                    # Tắt verify là quyết định có chủ ý của người cấu hình; urllib3 cảnh
                    # báo lại ở MỖI request nên không chặn thì log Odoo ngập cảnh báo và
                    # che mất những dòng đáng đọc. Chỉ tắt trong đúng lời gọi này, không
                    # tắt toàn cục để module khác không bị ảnh hưởng.
                    if not self.verify_ssl:
                        warnings.simplefilter('ignore', InsecureRequestWarning)
                    response = requests.request(
                        method, url, headers=headers, params=params, json=json_body,
                        timeout=self.timeout, verify=self.verify_ssl,
                    )
            except requests.exceptions.SSLError as exc:
                # Lỗi hay gặp nhất lúc cài đặt. Nói thẳng cách xử lý thay vì để người
                # dùng đọc traceback của requests.
                #
                # Thực tế đo được ngày 17/09/2026 với host mặc định: chứng chỉ do Sectigo
                # cấp cho *.innoway.vn (KHÔNG phải tự ký) nhưng đã hết hạn 07/03/2024, và
                # không có IP nào trong SAN. Nghĩa là gọi bằng IP thì sai host, mà đổi
                # sang tên miền cũng vẫn hỏng vì hết hạn — không có cách nào bật kiểm tra
                # mà vẫn gọi được, cho tới khi nhà cung cấp gia hạn chứng chỉ.
                raise VTrackingError(
                    'Lỗi chứng chỉ SSL khi gọi %s. Kiểm tra chứng chỉ của máy chủ bằng '
                    '`openssl s_client -connect <host>:<port>`: nếu nó hết hạn hoặc cấp '
                    'cho tên miền khác thì phải yêu cầu vTracking cấp lại, còn muốn dùng '
                    'ngay thì tắt "Kiểm tra chứng chỉ SSL" trong cấu hình — chấp nhận là '
                    'không xác thực được máy chủ. Chi tiết: %s' % (self.base_url, exc)
                ) from exc
            except requests.exceptions.RequestException as exc:
                last_error = VTrackingError('Không gọi được vTracking: %s' % exc)
                continue

            if response.status_code == 429:
                last_error = VTrackingError(
                    'vTracking trả 429 (quá nhiều request).', status_code=429,
                )
                _logger.warning('vTracking 429 tại %s, lùi lại lần %s.', path, attempt + 1)
                continue

            if response.status_code in (401, 403):
                raise VTrackingError(self._auth_error_message(response), status_code=response.status_code)

            if response.status_code != 200:
                raise VTrackingError(
                    'vTracking trả HTTP %s tại %s: %s' % (
                        response.status_code, path, (response.text or '')[:300],
                    ),
                    status_code=response.status_code,
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise VTrackingError(
                    'vTracking trả về dữ liệu không phải JSON tại %s.' % path
                ) from exc
            if not isinstance(payload, dict):
                raise VTrackingError('vTracking trả về JSON không đúng dạng tại %s.' % path)
            return payload

        raise last_error or VTrackingError('Gọi vTracking thất bại tại %s.' % path)
