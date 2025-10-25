# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import requests
import re
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


class WebsiteTrackingPublicDirect(http.Controller):

    @http.route(["/track"], type="http", auth="public", website=True)
    def track_form(self, **kw):
        return request.render("hlv_tracking_aftership.website_track_form", {})

    @http.route(["/track/search"], type="http", auth="public", methods=["GET", "POST"], website=True, csrf=False)
    def track_search(self, **post):
        params = request.params or {}
        query = (post.get("tracking_number") or params.get("tracking_number") or "").strip()
        slug_input = (post.get("slug") or params.get("slug") or "").strip()
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
            # Debug raw response when ?debug=1
            if (request.params or {}).get("debug") in ("1", "true", "yes"):
                return request.make_response(r.text, [("Content-Type", "application/json")])
            if not r.ok:
                # Try official API fallback when API key is configured
                api_key = request.env['ir.config_parameter'].sudo().get_param('aftership.api_key') or ''
                if api_key:
                    headers = {"Content-Type": "application/json", "as-api-key": api_key}
                    try:
                        data = None
                        if slug:
                            rr = requests.get(f"https://api.aftership.com/tracking/2025-07/trackings/{slug}/{number}?lang=vi", headers=headers, timeout=20)
                            if not rr.ok:
                                rc = requests.post(
                                    "https://api.aftership.com/tracking/2025-07/trackings",
                                    json={"tracking_number": number, "slug": slug},
                                    headers=headers,
                                    timeout=20,
                                )
                                ok = rc.status_code in (200, 201)
                                code = str(((rc.json().get("meta") if rc.content else {}) or {}).get("code")) if rc.content else ""
                                if not (ok or (rc.status_code == 400 and code == "4003")):
                                    _logger.warning("AfterShip official create failed %s: %s", rc.status_code, rc.text)
                                    error = f"Không lấy được tracking (direct {r.status_code}). Official: {rc.status_code} {rc.text}"
                                    return request.render("hlv_tracking_aftership.website_track_result", {
                                        "error": error, "data": {}, "number": number, "slug": slug or "",
                                    })
                                data = (rc.json().get("data") if rc.content else {}) or {}
                                tid = data.get("id")
                                if tid:
                                    r2 = requests.get(f"https://api.aftership.com/tracking/2025-07/trackings/{tid}?lang=vi", headers=headers, timeout=20)
                                    if r2.ok:
                                        data = r2.json().get("data") or data
                            else:
                                data = rr.json().get("data") or {}
                        else:
                            rc = requests.post(
                                "https://api.aftership.com/tracking/2025-07/trackings",
                                json={"tracking_number": number},
                                headers=headers,
                                timeout=20,
                            )
                            ok = rc.status_code in (200, 201)
                            code = str(((rc.json().get("meta") if rc.content else {}) or {}).get("code")) if rc.content else ""
                            if not (ok or (rc.status_code == 400 and code == "4003")):
                                _logger.warning("AfterShip official create failed %s: %s", rc.status_code, rc.text)
                                error = f"Không tạo được tracking (direct {r.status_code}): {rc.status_code} {rc.text}"
                                return request.render("hlv_tracking_aftership.website_track_result", {
                                    "error": error, "data": {}, "number": number, "slug": slug or "",
                                })
                            data = (rc.json().get("data") if rc.content else {}) or {}
                            tid = data.get("id")
                            if tid:
                                r2 = requests.get(f"https://api.aftership.com/tracking/2025-07/trackings/{tid}?lang=vi", headers=headers, timeout=20)
                                if r2.ok:
                                    data = r2.json().get("data") or data

                        # Normalize and render
                        tracking = (data or {}).get('tracking') or data or {}
                        checkpoints = list(reversed(tracking.get('checkpoints') or []))
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": None,
                            "data": tracking or {},
                            "number": number,
                            "slug": slug or "",
                            "checkpoints": checkpoints,
                        })
                    except Exception as e:
                        _logger.warning("AfterShip official fallback failed: %s", e)
                        error = f"Không lấy được tracking (direct {r.status_code}). Lỗi official: {e}"
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, "data": {}, "number": number, "slug": slug or "",
                        })
                # No API key or fallback failed
                _logger.warning("AfterShip direct error %s: %s", r.status_code, r.text)
                error = f"Không lấy được tracking: {r.status_code} {r.text}"
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": error, "data": {}, "number": number, "slug": slug or "",
                })
            j = r.json() or {}
            items = ((j.get("data") or {}).get("direct_trackings") or [])
            if not items:
                _logger.info("AfterShip direct empty for %s/%s: %s", slug, number, r.text)
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
