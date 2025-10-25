# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import requests
import re


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


class WebsiteTrackingPublicDirect(http.Controller):

    @http.route(['/track'], type='http', auth='public', website=True)
    def track_form(self, **kw):
        return request.render("hlv_tracking_aftership.website_track_form", {})

    @http.route(['/track/search'], type='http', auth='public', methods=['GET', 'POST'], website=True, csrf=False)
    def track_search(self, **post):
        params = request.params or {}
        query = (post.get('tracking_number') or params.get('tracking_number') or '').strip()
        slug_input = (post.get('slug') or params.get('slug') or '').strip()
        error = None

        number = None
        slug = slug_input or None

        try:
            if not _looks_like_tracking(query):
                Picking = request.env["stock.picking"].sudo()
                pick = Picking.search(["|", ("name", "=", query), ("origin", "=", query)], limit=1)
                if not pick:
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

            # Call AfterShip public direct API (no API key)
            url = "https://track.aftership.com/api/v2/direct-trackings/batch"
            payload = {
                "direct_trackings": [{
                    "tracking_number": number,
                    **({"slug": slug} if slug else {}),
                    "additional_fields": {},
                }],
                "translate_to": "vi",
            }
            headers_direct = {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.aftership.com/",
            }
            r = requests.post(url, json=payload, headers=headers_direct, timeout=25)
            if not r.ok:
                error = f"Không lấy được tracking: {r.status_code} {r.text}"
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": error, "data": {}, "number": number, "slug": slug or "",
                })
            j = r.json() or {}
            items = ((j.get("data") or {}).get("direct_trackings") or [])
            if not items:
                error = "Không có dữ liệu từ AfterShip."
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": error, "data": {}, "number": number, "slug": slug or "",
                })

            tracking = (items[0] or {}).get("tracking") or {}
            tracking["slug"] = tracking.get("slug") or slug or ""
            tracking["tracking_number"] = tracking.get("tracking_number") or number
            tracking["status"] = tracking.get("latest_status") or tracking.get("status")

        except Exception as e:
            error = f"Lỗi kết nối: {e}"
            return request.render("hlv_tracking_aftership.website_track_result", {
                "error": error, "data": {}, "number": query, "slug": slug_input,
            })

        checkpoints = list(reversed(tracking.get('checkpoints') or []))
        return request.render("hlv_tracking_aftership.website_track_result", {
            "error": None,
            "data": tracking or {},
            "number": number or query,
            "slug": slug or slug_input,
            "checkpoints": checkpoints,
        })

