# -*- coding: utf-8 -*-
"""Gọi API web MISA cho việc lấy hoá đơn mua vào đã thanh toán — một lần bấm gọi MISA hàng chục / hàng trăm lần liền.

Vì sao không gọi thẳng misa.api.utils._fetch_misa_json_with_session_retry như các tính năng MISA khác: hàm đó mở kết
nối mới cho MỖI request (requests.post) và không thử lại khi lỗi kết nối. Case thật trên prd (2026-10-23): đang lượt
"lấy cho mọi NCC" thì kết nối IPv4 tới actapp.misa.vn hỏng thoáng qua → cả lần bấm hỏng. Ở đây:
- một requests.Session cho cả lần bấm (giữ kết nối — bớt bắt tay TLS, bớt dồn MISA);
- nghỉ PAUSE_SECONDS giữa các lần gọi;
- lỗi kết nối / hết giờ → thử lại tối đa len(RETRY_WAITS) lần, nghỉ tăng dần, không quá hạn chót của lần bấm.
Token, header, cách đọc phản hồi vẫn của misa.api.utils / misa.config (không chép lại): token cache
_get_misa_token_cached, header get_default_headers, kiểm Success bằng _misa_json_or_raise; phản hồi lỗi thì đăng nhập
lại đúng một lần như _fetch_misa_json_with_session_retry.

Lưu ý đọc log: máy prd không có đường IPv6 ra ngoài — kết nối hỏng sẽ hiện "[Errno 101] Network is unreachable" (lỗi
của địa chỉ IPv6 thử SAU CÙNG), che lỗi IPv4 thật. Log ở đây ghi kèm số giây đã chờ: ~CONNECT_TIMEOUT giây = IPv4 bị
treo (MISA bỏ gói tin), gần 0 giây = bị từ chối / mạng rớt."""

import logging
import time

import requests

from odoo.addons.misa_invoice_status_report.models.misa_api_utils_ext import _misa_json_or_raise

_logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
PAUSE_SECONDS = 0.25
# Giây nghỉ trước lần thử lại thứ 1, 2.
RETRY_WAITS = (2, 5)


class MisaCallError(Exception):
    """Không lấy được dữ liệu MISA sau khi đã thử lại (mất kết nối, MISA trả lỗi, hết phiên)."""


class MisaClient:
    """Dùng trong with: with MisaClient(env, deadline) as client: client.post_json(url, payload, context).
    deadline: time.monotonic() hạn chót của lần bấm — quá hạn thì không thử lại nữa."""

    def __init__(self, env, deadline):
        self._utils = env["misa.api.utils"]
        self._config = env["misa.config"]
        self._deadline = deadline
        self._session = requests.Session()
        self._last_call = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._session.close()

    def _headers(self, force_refresh=False):
        return self._config.get_default_headers(self._utils._get_misa_token_cached(force_refresh=force_refresh))

    def post_json(self, url, payload, context):
        """POST rồi trả JSON MISA (Success=true). Phản hồi lỗi (hết phiên, 401, Success=false) → đăng nhập lại một lần
        rồi gọi lại. Vẫn lỗi / không kết nối được → MisaCallError."""
        try:
            return _misa_json_or_raise(self._post(url, payload, self._headers()), context)
        except MisaCallError:
            raise
        except Exception as first:  # MISA "quên" phiên dù token chưa hết hạn theo đồng hồ — xem session_retry
            _logger.warning("MISA %s lỗi lần 1 (%s) — đăng nhập lại và thử lại.", context, str(first)[:300])
        try:
            return _misa_json_or_raise(self._post(url, payload, self._headers(force_refresh=True)), context)
        except MisaCallError:
            raise
        except Exception as exc:
            raise MisaCallError("MISA trả lỗi (%s): %s" % (context, str(exc)[:300])) from exc

    def _post(self, url, payload, headers):
        """Một POST, thử lại khi lỗi kết nối / hết giờ (không thử lại khi quá hạn chót)."""
        attempt = 0
        while True:
            self._pace()
            started = time.monotonic()
            try:
                return self._session.post(url, headers=headers, json=payload, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            except (requests.ConnectionError, requests.Timeout) as exc:
                waited = time.monotonic() - started
                _logger.warning("MISA %s: %s sau %.1fs (lần %d)", url.rsplit("/", 1)[-1], type(exc).__name__,
                                waited, attempt + 1)
                if attempt >= len(RETRY_WAITS) or time.monotonic() + RETRY_WAITS[attempt] > self._deadline:
                    raise MisaCallError("Không kết nối được MISA (%s sau %.0f giây, đã thử %d lần)"
                                        % (type(exc).__name__, waited, attempt + 1)) from exc
                time.sleep(RETRY_WAITS[attempt])
                attempt += 1

    def _pace(self):
        wait = PAUSE_SECONDS - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
