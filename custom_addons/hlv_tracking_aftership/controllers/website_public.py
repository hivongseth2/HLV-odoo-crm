# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import requests
import re

AFTERSHIP_API_BASE = "https://api.aftership.com/tracking/2025-07"

def _looks_like_tracking(number: str) -> bool:
    if not number:
        return False
    # Heuristics: có tiền tố hãng hoặc đủ dài, không chỉ số
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

    @http.route(['/track/search'], type='http', auth='public', methods=['POST'], website=True, csrf=True)
    def track_search(self, **post):
        """
        Người dùng nhập:
         - Mã vận đơn (VD: SPXVN..., JT...) -> tra trực tiếp
         - Hoặc MÃ ĐƠN NỘI BỘ (VD: KBC/OUT/01931) -> tìm Stock Picking/Delivery có name/origin = mã này,
           lấy tracking_number + tracking_slug rồi mới tra AfterShip
        """
        query = (post.get('tracking_number') or '').strip()
        slug_input = (post.get('slug') or '').strip()
        api_key = request.env['ir.config_parameter'].sudo().get_param('aftership.api_key') or ''
        error = None
        data = {}

        if not api_key:
            error = "Hệ thống chưa cấu hình API key."
            return request.render("hlv_tracking_aftership.website_track_result", {
                "error": error, "data": {}, "number": query, "slug": slug_input,
            })

        headers = {"Content-Type": "application/json", "as-api-key": api_key}

        number = None
        slug = slug_input or None

        try:
            # 1) Nếu không giống tracking number => xem như mã đơn nội bộ, tra Odoo để lấy tracking
            if not _looks_like_tracking(query):
                Picking = request.env["stock.picking"].sudo()
                pick = Picking.search(["|", ("name", "=", query), ("origin", "=", query)], limit=1)
                if not pick:
                    error = f"Không tìm thấy phiếu giao hàng cho mã: {query}"
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": query, "slug": slug_input,
                    })
                number = (pick.tracking_number or "").strip()
                slug = (pick.tracking_slug or slug or _guess_slug(number) or "").strip()
                if not number:
                    error = f"Đơn {query} chưa có mã vận đơn."
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": query, "slug": slug,
                    })
            else:
                # 2) Người dùng nhập trực tiếp mã vận đơn
                number = query
                if not slug:
                    slug = _guess_slug(number)

            # 3) Gọi AfterShip (ưu tiên GET theo slug+number; nếu không có slug thì idempotent create rồi GET theo id)
            if slug:
                url = f"{AFTERSHIP_API_BASE}/trackings/{slug}/{number}?lang=vi"
                r = requests.get(url, headers=headers, timeout=20)
                if not r.ok:
                    # fallback: thử create (đề phòng chưa đăng ký tracking)
                    rc = requests.post(f"{AFTERSHIP_API_BASE}/trackings",
                                       json={"tracking_number": number, "slug": slug},
                                       headers=headers, timeout=20)
                    # Nếu 4003 (đã tồn tại) vẫn tiếp tục lấy chi tiết
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
                # Không có slug -> create để AfterShip auto-detect, rồi GET theo id
                rc = requests.post(f"{AFTERSHIP_API_BASE}/trackings",
                                   json={"tracking_number": number},
                                   headers=headers, timeout=20)
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

        return request.render("hlv_tracking_aftership.website_track_result", {
            "error": error,
            "data": data or {},
            "number": number or query,
            "slug": slug or slug_input,
        })
