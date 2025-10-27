# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import requests
import re
import logging

_logger = logging.getLogger(__name__)

AFTERSHIP_API_BASE = "https://api.aftership.com/tracking/2025-07"


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
        return request.render("hlv_tracking_aftership.website_track_form", {})

    @http.route(['/track/search'], type='http', auth='public', methods=['GET', 'POST'], website=True, csrf=False)
    def track_search(self, **post):
        # Support both GET and POST submissions
        params = request.params or {}
        query = (post.get('tracking_number') or params.get('tracking_number') or '').strip()
        slug_input = (post.get('slug') or params.get('slug') or '').strip()
        
        _logger.info(f"=== TRACK SEARCH START ===")
        _logger.info(f"Query: {query}")
        _logger.info(f"Slug input: {slug_input}")
        _logger.info(f"POST data: {post}")
        _logger.info(f"GET params: {params}")
        
        api_key = request.env['ir.config_parameter'].sudo().get_param('aftership.api_key') or ''
        error = None
        data = {}

        if not api_key:
            error = "Hệ thống chưa cấu hình API key."
            _logger.error(f"Missing API key!")
            return request.render("hlv_tracking_aftership.website_track_result", {
                "error": error, "data": {}, "number": query, "slug": slug_input,
            })
        
        if not query:
            error = "Vui lòng nhập mã vận đơn hoặc mã đơn hàng."
            _logger.warning(f"Empty query!")
            return request.render("hlv_tracking_aftership.website_track_result", {
                "error": error, "data": {}, "number": "", "slug": slug_input,
            })

        headers = {"Content-Type": "application/json", "as-api-key": api_key}

        number = None
        slug = slug_input or None

        try:
            if not _looks_like_tracking(query):
                Picking = request.env["stock.picking"].sudo()
                pick = Picking.search(["|", ("name", "=", query), ("origin", "=", query)], limit=1)
                if not pick:
                    # Fallback: tìm theo Đơn bán hàng
                    SaleOrder = request.env["sale.order"].sudo()
                    order = SaleOrder.search(["|", ("name", "=", query), ("client_order_ref", "=", query)], limit=1)
                    if not order:
                        error = f"Không tìm thấy phiếu giao hàng hoặc đơn hàng cho mã: {query}"
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, "data": {}, "number": query, "slug": slug_input,
                        })
                    number = (order.tracking_number or "").strip()
                    slug = (order.tracking_slug or slug or _guess_slug(number) or "").strip()
                    if not number:
                        error = f"Đơn {query} chưa có mã vận đơn."
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, "data": {}, "number": query, "slug": slug,
                        })
                else:
                    number = (pick.tracking_number or "").strip()
                    slug = (pick.tracking_slug or slug or _guess_slug(number) or "").strip()
                    if not number:
                        error = f"Đơn {query} chưa có mã vận đơn."
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, "data": {}, "number": query, "slug": slug,
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
                        error = f"Lỗi truy vấn: {r.status_code} {r.text}"
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, "data": {}, "number": number, "slug": slug,
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
                rc = requests.post(
                    f"{AFTERSHIP_API_BASE}/trackings",
                    json={"tracking_number": number},
                    headers=headers,
                    timeout=20,
                )
                if not (rc.status_code in (200, 201) or (rc.status_code == 400 and str((rc.json().get("meta") or {}).get("code")) == "4003")):
                    error = f"Không tạo được tracking: {rc.status_code} {rc.text}"
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": number, "slug": "",
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
        tracking['tag_vn'] = _vi_status(tracking.get('tag') or tracking.get('status'), tracking.get('status'))

        _logger.info(f"=== TRACK SEARCH RESULT ===")
        _logger.info(f"Error: {error}")
        _logger.info(f"Tracking data: {tracking}")
        _logger.info(f"Checkpoints count: {len(checkpoints)}")

        return request.render("hlv_tracking_aftership.website_track_result", {
            "error": error,
            "data": tracking or {},
            "number": number or query,
            "slug": slug or slug_input,
            "checkpoints": checkpoints,
        })
