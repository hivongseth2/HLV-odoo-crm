# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

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

    @http.route(['/track/search'], type='http', auth='public', methods=['POST'], website=True, csrf=False)
    def track_search(self, **post):
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
                number = query
                if not slug:
                    slug = _guess_slug(number)

            if slug:
                url = f"{AFTERSHIP_API_BASE}/trackings/{slug}/{number}?lang=vi"
                r = requests.get(url, headers=headers, timeout=20)
                if not r.ok:
                    rc = requests.post(f"{AFTERSHIP_API_BASE}/trackings",
                                       json={"tracking_number": number, "slug": slug},
                                       headers=headers, timeout=20)
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

        tracking = (data or {}).get('tracking') or data or {}
        checkpoints = (tracking.get('checkpoints') or [])
        for cp in checkpoints or []:
            cp['message'] = _polish_message(cp.get('message'))
            cp['status_vn'] = _vi_status(cp.get('status'), _polish_message(cp.get('message')))
        tracking['tag_vn'] = _vi_status(tracking.get('tag') or tracking.get('status'), tracking.get('status'))

        return request.render("hlv_tracking_aftership.website_track_result", {
            "error": error,
            "data": tracking or {},
            "number": number or query,
            "slug": slug or slug_input,
            "checkpoints": checkpoints,
        })