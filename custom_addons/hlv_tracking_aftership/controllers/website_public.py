# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import requests

AFTERSHIP_API_BASE = "https://api.aftership.com/tracking/2025-07"

class WebsiteTrackingPublic(http.Controller):
    @http.route(['/track'], type='http', auth='public', website=True)
    def track_form(self, **kw):
        return request.render("hlv_tracking_aftership.website_track_form", {})

    @http.route(['/track/search'], type='http', auth='public', methods=['POST'], website=True, csrf=True)
    def track_search(self, **post):
        number = (post.get('tracking_number') or '').strip()
        slug   = (post.get('slug') or '').strip()  # có thể để trống để auto-detect
        api_key = request.env['ir.config_parameter'].sudo().get_param('aftership.api_key') or ''
        error = None
        data = {}
        if not api_key:
            error = "Hệ thống chưa cấu hình API key."
        elif not number:
            error = "Bạn chưa nhập mã vận đơn."
        else:
            headers = {"Content-Type": "application/json", "as-api-key": api_key}
            # Nếu người dùng không nhập slug => dùng endpoint by number, else by id sẽ cần id
            # Ở đây đơn giản: nếu có slug thì gọi /trackings/{slug}/{number}, nếu không -> create (đăng ký) rồi GET by created id
            try:
                if slug:
                    url = f"{AFTERSHIP_API_BASE}/trackings/{slug}/{number}?lang=vi"
                    r = requests.get(url, headers=headers, timeout=20)
                    if not r.ok:
                        error = f"Lỗi truy vấn: {r.status_code} {r.text}"
                    else:
                        data = r.json().get("data", {}) or {}
                else:
                    # auto-detect: tạo (idempotent) rồi lấy theo id
                    url_create = f"{AFTERSHIP_API_BASE}/trackings"
                    rc = requests.post(url_create, json={"tracking_number": number}, headers=headers, timeout=20)
                    if rc.status_code not in (200,201):
                        # nếu đã tồn tại (4003) thì vẫn tiếp tục
                        try:
                            payload = rc.json()
                        except Exception:
                            payload = {}
                        if not (rc.status_code == 400 and str((payload.get("meta") or {}).get("code"))=="4003"):
                            error = f"Không tạo được tracking: {rc.status_code} {rc.text}"
                        data = (payload.get("data") or {})
                    else:
                        data = (rc.json().get("data") or {})
                # Nếu có id -> lấy bản có lang=vi để hiển thị đẹp pl
                tid = data.get("id")
                if not error and tid:
                    url = f"{AFTERSHIP_API_BASE}/trackings/{tid}?lang=vi"
                    r2 = requests.get(url, headers=headers, timeout=20)
                    if r2.ok:
                        data = r2.json().get("data", {}) or data
            except Exception as e:
                error = f"Lỗi kết nối: {e}"
        return request.render("hlv_tracking_aftership.website_track_result", {
            "error": error,
            "data": data,
            "number": number,
            "slug": slug,
        })
