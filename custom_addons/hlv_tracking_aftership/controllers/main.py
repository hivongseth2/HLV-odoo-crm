# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import requests
import re
import logging
from datetime import datetime, timezone, timedelta

_WD_VI = ["Th 2", "Th 3", "Th 4", "Th 5", "Th 6", "Th 7", "CN"]
_TZ_VN = timezone(timedelta(hours=7))

def _parse_iso8601(s: str):
    """Parse ISO 8601 như '2025-10-21T09:58:09+07:00' hoặc '...Z' → datetime aware."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def _format_absolute_vi(dt: datetime) -> str:
    """Trả 'HH:MM DD/MM/YYYY (Th x)' ở múi giờ Việt Nam."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ_VN)
    dt_vn = dt.astimezone(_TZ_VN)
    wd = _WD_VI[dt_vn.weekday()]  # Monday=0 → Th 2
    return f"{dt_vn:%H:%M %d/%m/%Y} ({wd})"


_logger = logging.getLogger(__name__)

AFTERSHIP_API_BASE = "https://api.aftership.com/tracking/2024-07"

VI_STATUS_LABELS = {
    "INFORECEIVED": "Đơn hàng đã được tạo trên hệ thống",
    "INTRANSIT": "Đang trung chuyển",
    "OUTFORDELIVERY": "Nhân viên đang giao hàng",
    "DELIVERED": "Đã giao thành công",
    "AVAILABLEFORPICKUP": "Sẵn sàng để lấy hàng",
    "FAILEDATTEMPT": "Giao hàng chưa thành công",
    "EXCEPTION": "Phát sinh sự cố trong quá trình giao",
    "PENDING": "Đang chờ hãng vận chuyển xử lý",
    "READYFORPICKUP": "Sẵn sàng để lấy hàng",
    "RETURNEDTOSELLER": "Đơn hàng đã được hoàn về",
}

REPLACEMENTS = (
    ("Thực tệ", "Đơn hàng"),
    ("Bưu kiện của bạn", "Kiện hàng của bạn"),
    ("đang được chuyển phát nhanh", "đang trên đường giao"),
    ("đã được nhận", "đã được tiếp nhận"),
)

def _polish_message(message: str) -> str:
    msg = (message or "").strip()
    for old, new in REPLACEMENTS:
        msg = msg.replace(old, new)
    return msg

def _vi_status(tag: str, fallback: str = "") -> str:
    key = (tag or "").replace(" ", "").upper()
    if key in VI_STATUS_LABELS:
        return VI_STATUS_LABELS[key]
    return fallback or tag or ""

def _looks_like_tracking(number: str) -> bool:
    if not number:
        return False
    prefixes = ("SPX", "SPXVN", "JT", "JTEXP", "VT", "GHN", "GHTK")
    if number.upper().startswith(prefixes):
        return True
    return len(number) >= 10 and bool(re.search(r"[A-Za-z]", number))

def _guess_slug(number: str) -> str:
    n = (number or "").upper()
    if n.startswith(("SPX", "SPXVN")):
        return "spx-vn"
    if n.startswith(("JT", "JTEXP")):
        return "jtexpress-vn"
    if n.startswith("VT"):
        return "viettelpost-vn"
    if n.startswith(("GHN",)):
        return "ghn"
    if n.startswith(("GHTK",)):
        return "giaohangtietkiem"
    return None


class WebsiteTrackingPublic(http.Controller):

    @http.route(['/track'], type='http', auth='public', website=True)
    def track_form(self, **kw):
        return request.render("hlv_tracking_aftership.website_track_page", {
            "error": None,
            "data": None,
            "number": "",
            "slug": "",
            "checkpoints": [],
        })

    @http.route(['/track/search'], type='http', auth='public', methods=['GET', 'POST'], website=True, csrf=False)
    def track_search(self, **post):
        params = request.params or {}
        query = (post.get('tracking_number') or params.get('tracking_number') or '').strip()
        slug_input = (post.get('slug') or params.get('slug') or '').strip()
        
        _logger.info(f"=== TRACK SEARCH START ===")
        _logger.info(f"Query: {query}")
        _logger.info(f"Slug input: {slug_input}")
        
        api_key = request.env['ir.config_parameter'].sudo().get_param('aftership.api_key') or ''
        error = None
        data = {}

        if not api_key:
            error = "Hệ thống chưa cấu hình API key."
            _logger.error(f"Missing API key!")
            return request.render("hlv_tracking_aftership.website_track_page", {
                "error": error,
                "data": {},
                "number": query,
                "slug": slug_input,
                "checkpoints": [],
            })
        
        if not query:
            error = "Vui lòng nhập mã vận đơn hoặc mã đơn hàng."
            _logger.warning(f"Empty query!")
            return request.render("hlv_tracking_aftership.website_track_page", {
                "error": error,
                "data": {},
                "number": "",
                "slug": slug_input,
                "checkpoints": [],
            })

        headers = {"Content-Type": "application/json", "as-api-key": api_key}
        number = None
        # Chuẩn hóa slug_input: chỉ chấp nhận nếu không rỗng
        slug = slug_input.strip() if slug_input and slug_input.strip() else None

        try:
            if not _looks_like_tracking(query):
                Picking = request.env["stock.picking"].sudo()
                pick = Picking.search(["|", ("name", "=", query), ("origin", "=", query)], limit=1)
                if not pick:
                    SaleOrder = request.env["sale.order"].sudo()
                    order = SaleOrder.search(["|", ("name", "=", query), ("client_order_ref", "=", query)], limit=1)
                    if not order:
                        error = f"Không tìm thấy phiếu giao hàng hoặc đơn hàng cho mã: {query}"
                        return request.render("hlv_tracking_aftership.website_track_page", {
                            "error": error,
                            "data": {},
                            "number": query,
                            "slug": slug_input,
                            "checkpoints": [],
                        })
                    number = (order.tracking_number or "").strip()
                    # Ưu tiên: tracking_slug từ DB -> slug_input -> guess từ number
                    db_slug = (order.tracking_slug or "").strip()
                    slug = db_slug if db_slug else (slug if slug else _guess_slug(number))
                    if not number:
                        error = f"Đơn {query} chưa có mã vận đơn."
                        return request.render("hlv_tracking_aftership.website_track_page", {
                            "error": error,
                            "data": {},
                            "number": query,
                            "slug": slug or "",
                            "checkpoints": [],
                        })
                else:
                    number = (pick.tracking_number or "").strip()
                    # Ưu tiên: tracking_slug từ DB -> slug_input -> guess từ number
                    db_slug = (pick.tracking_slug or "").strip()
                    slug = db_slug if db_slug else (slug if slug else _guess_slug(number))
                    if not number:
                        error = f"Đơn {query} chưa có mã vận đơn."
                        return request.render("hlv_tracking_aftership.website_track_page", {
                            "error": error,
                            "data": {},
                            "number": query,
                            "slug": slug or "",
                            "checkpoints": [],
                        })
            else:
                number = query
                if not slug:
                    slug = _guess_slug(number)

            if slug:
                url = f"{AFTERSHIP_API_BASE}/trackings/{slug}/{number}?lang=vi"
                _logger.info(f"Calling AfterShip API: {url}")
                r = requests.get(url, headers=headers, timeout=20)
                _logger.info(f"Response status: {r.status_code}")
                if not r.ok:
                    _logger.warning(f"Failed to get tracking, trying to create: {r.text}")
                    rc = requests.post(
                        f"{AFTERSHIP_API_BASE}/trackings",
                        json={"tracking_number": number, "slug": slug},
                        headers=headers,
                        timeout=20,
                    )
                    if not (rc.status_code in (200, 201) or (rc.status_code == 400 and str((rc.json().get("meta") or {}).get("code")) == "4003")):
                        error = f"Lỗi truy vấn: {rc.status_code} {rc.text}"
                        return request.render("hlv_tracking_aftership.website_track_page", {
                            "error": error,
                            "data": {},
                            "number": number,
                            "slug": slug or "",
                            "checkpoints": [],
                        })
                    data = (rc.json().get("data") or {})
                    tid = data.get("id")
                    if tid:
                        r2 = requests.get(f"{AFTERSHIP_API_BASE}/trackings/{tid}?lang=vi", headers=headers, timeout=20)
                        if r2.ok:
                            data = r2.json().get("data") or data
                else:
                    data = r.json().get("data") or {}
            else:
                # Không có slug, tạo tracking mà không chỉ định slug để AfterShip tự detect
                _logger.info(f"No slug provided, creating tracking without slug for number: {number}")
                rc = requests.post(
                    f"{AFTERSHIP_API_BASE}/trackings",
                    json={"tracking_number": number},
                    headers=headers,
                    timeout=20,
                )
                if not (rc.status_code in (200, 201) or (rc.status_code == 400 and str((rc.json().get("meta") or {}).get("code")) == "4003")):
                    error = f"Không tạo được tracking: {rc.status_code} {rc.text}"
                    return request.render("hlv_tracking_aftership.website_track_page", {
                        "error": error,
                        "data": {},
                        "number": number,
                        "slug": "",
                        "checkpoints": [],
                    })
                data = (rc.json().get("data") or {})
                tid = data.get("id")
                if tid:
                    r2 = requests.get(f"{AFTERSHIP_API_BASE}/trackings/{tid}?lang=vi", headers=headers, timeout=20)
                    if r2.ok:
                        data = r2.json().get("data") or data

        except Exception as e:
            error = f"Lỗi kết nối: {e}"
            _logger.exception(f"Exception in track_search: {e}")

        tracking = (data or {}).get('tracking') or data or {}
        checkpoints = list(reversed(tracking.get('checkpoints') or []))
        for cp in checkpoints:
            cp['message'] = _polish_message(cp.get('message'))
            cp['status_vn'] = _vi_status(cp.get('status'), _polish_message(cp.get('message')))
            ts = cp.get('checkpoint_time') or cp.get('created_at') or cp.get('time')
            dt = _parse_iso8601(ts)
            cp['time_display'] = _format_absolute_vi(dt)
        tracking['tag_vn'] = _vi_status(tracking.get('tag') or tracking.get('status'), tracking.get('status'))

        _logger.info(f"=== TRACK SEARCH RESULT ===")
        _logger.info(f"Error: {error}")
        _logger.info(f"Tracking data: {tracking}")
        _logger.info(f"Checkpoints count: {len(checkpoints)}")

        # Lấy slug từ tracking data nếu có, fallback về slug đã xác định hoặc slug_input
        final_slug = tracking.get('slug') or slug or slug_input or ""

        return request.render("hlv_tracking_aftership.website_track_page", {
            "error": error,
            "data": tracking or {},
            "number": number or query,
            "slug": final_slug,
            "checkpoints": checkpoints,
        })