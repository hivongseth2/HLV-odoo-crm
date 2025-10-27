# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import requests
import re
import logging

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
    # Các biến thể khác của cùng status
    "RETURN_TO_SENDER": "Đơn hàng đã được hoàn về",
    "RETURNED_TO_SENDER": "Đơn hàng đã được hoàn về",
    # Các status khác phổ biến
    "ARRIVALSCAN": "Kiện hàng đã được tiếp nhận",
    "ARRIVAL": "Kiện hàng đã được tiếp nhận",
    "PICKED_UP": "Kiện hàng đã được lấy",
    "PICKEDUP": "Kiện hàng đã được lấy",
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
    """Convert status tag to Vietnamese. Handles various case formats."""
    if not tag:
        return fallback or ""
    # Chuẩn hóa: xóa space, convert thành uppercase, thay dash/dot bằng underscore
    key = (tag or "").strip().replace(" ", "").replace("-", "_").replace(".", "_").upper()
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
                    try:
                        db_slug_raw = order.tracking_slug
                        _logger.info(f"Order tracking_slug raw value: {db_slug_raw} (type: {type(db_slug_raw)})")
                        # Chỉ chấp nhận nếu là string hợp lệ
                        if isinstance(db_slug_raw, str):
                            db_slug = db_slug_raw.strip()
                        else:
                            _logger.warning(f"Invalid tracking_slug type from order: {type(db_slug_raw)}")
                            db_slug = ""
                    except Exception as e:
                        _logger.error(f"Error getting tracking_slug from order: {e}")
                        db_slug = ""
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
                    try:
                        db_slug_raw = pick.tracking_slug
                        _logger.info(f"Picking tracking_slug raw value: {db_slug_raw} (type: {type(db_slug_raw)})")
                        # Chỉ chấp nhận nếu là string hợp lệ
                        if isinstance(db_slug_raw, str):
                            db_slug = db_slug_raw.strip()
                        else:
                            _logger.warning(f"Invalid tracking_slug type from picking: {type(db_slug_raw)}")
                            db_slug = ""
                    except Exception as e:
                        _logger.error(f"Error getting tracking_slug from picking: {e}")
                        db_slug = ""
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

            # Đảm bảo slug là string hoặc None - KHÔNG BAO GIỜ là object hoặc method
            if slug and not isinstance(slug, str):
                _logger.error(f"Invalid slug type before API call: {type(slug)}, value: {slug}")
                slug = None

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
            # Sử dụng tag nếu có, fallback sang status
            checkpoint_tag = cp.get('tag') or cp.get('status') or ""
            cp['status_vn'] = _vi_status(checkpoint_tag, _polish_message(cp.get('message')))
        tracking['tag_vn'] = _vi_status(tracking.get('tag') or tracking.get('status'), tracking.get('status'))

        # Lấy slug từ tracking data nếu có, fallback về slug đã xác định hoặc slug_input
        # Đảm bảo final_slug luôn là string, không bao giờ là method/object
        tracking_slug = tracking.get('slug')
        if tracking_slug and not isinstance(tracking_slug, str):
            _logger.warning(f"Invalid slug type in tracking data: {type(tracking_slug)}, value: {tracking_slug}")
            tracking_slug = None
        
        final_slug = tracking_slug or (slug if slug and isinstance(slug, str) else None) or (slug_input if slug_input and isinstance(slug_input, str) else None) or ""

        return request.render("hlv_tracking_aftership.website_track_page", {
            "error": error,
            "data": tracking or {},
            "number": number or query,
            "slug": final_slug,
            "checkpoints": checkpoints,
        })