# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import requests
import re

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
        return request.render("hlv_tracking_aftership.website_track_form", {})

    @http.route(['/track/search'], type='http', auth='public', methods=['GET', 'POST'], website=True, csrf=False)
    def track_search(self, **post):
        # Support both GET and POST submissions
        params = request.params or {}
        query = (post.get('tracking_number') or params.get('tracking_number') or '').strip()
        slug_input = (post.get('slug') or params.get('slug') or '').strip()
        force_refresh = (post.get('force_refresh') or params.get('force_refresh') or '').strip() == '1'
        
        error = None
        data = {}
        number = None
        slug = slug_input or None
        last_update = None

        try:
            # Bước 1: Ưu tiên tìm kiếm trong database theo mã đơn hàng hoặc mã vận đơn
            Picking = request.env["stock.picking"].sudo()
            SaleOrder = request.env["sale.order"].sudo()
            
            pick = None
            order = None
            
            # Tìm trong stock.picking
            pick = Picking.search([
                '|', ('name', '=', query),
                '|', ('origin', '=', query),
                ('tracking_number', '=', query)
            ], limit=1)
            
            # Nếu picking không có, tìm trong sale.order
            if not pick:
                order = SaleOrder.search([
                    '|', ('name', '=', query),
                    '|', ('client_order_ref', '=', query),
                    ('tracking_number', '=', query)
                ], limit=1)
                
                # Nếu tìm thấy order, lấy picking từ order
                if order:
                    pick = order.picking_ids.filtered(lambda p: p.tracking_number)[:1]
            
            # Bước 2: Nếu tìm thấy picking/order và có tracking_payload
            if pick and pick.tracking_payload and not force_refresh:
                # Sử dụng dữ liệu từ database (KHÔNG GỌI API)
                tracking = pick.tracking_payload
                number = pick.tracking_number
                slug = pick.tracking_slug
                last_update = pick.tracking_last_update
                
                checkpoints = list(reversed(tracking.get('checkpoints') or []))
                for cp in checkpoints:
                    cp['message'] = _polish_message(cp.get('message'))
                    cp['status_vn'] = _vi_status(cp.get('tag') or cp.get('status'), _polish_message(cp.get('message')))
                tracking['tag_vn'] = _vi_status(tracking.get('tag') or tracking.get('status'), tracking.get('status'))
                
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": None,
                    "data": tracking or {},
                    "number": number,
                    "slug": slug or "",
                    "checkpoints": checkpoints,
                    "last_update": last_update,
                    "from_cache": True,
                })
            
            # Bước 2b: Nếu có order nhưng chưa có tracking_payload và không force refresh
            if order and order.tracking_payload and not force_refresh:
                tracking = order.tracking_payload
                number = order.tracking_number
                slug = order.tracking_slug
                last_update = order.tracking_last_update
                
                checkpoints = list(reversed(tracking.get('checkpoints') or []))
                for cp in checkpoints:
                    cp['message'] = _polish_message(cp.get('message'))
                    cp['status_vn'] = _vi_status(cp.get('tag') or cp.get('status'), _polish_message(cp.get('message')))
                tracking['tag_vn'] = _vi_status(tracking.get('tag') or tracking.get('status'), tracking.get('status'))
                
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": None,
                    "data": tracking or {},
                    "number": number,
                    "slug": slug or "",
                    "checkpoints": checkpoints,
                    "last_update": last_update,
                    "from_cache": True,
                })
            
            # Bước 3: Nếu có picking/order nhưng chưa có payload HOẶC force_refresh
            if pick or order:
                record = pick or order
                if record.tracking_number:
                    number = record.tracking_number
                    slug = record.tracking_slug or slug_input
                    
                    # Nếu chưa đăng ký AfterShip, đăng ký ngay
                    if not record.aftership_id:
                        try:
                            record.action_register_tracking_aftership()
                        except Exception as e:
                            error = f"Lỗi đăng ký tracking: {e}"
                            return request.render("hlv_tracking_aftership.website_track_result", {
                                "error": error, "data": {}, "number": number, "slug": slug or "",
                            })
                    else:
                        # Refresh data từ AfterShip
                        try:
                            record.action_refresh_tracking_aftership()
                        except Exception as e:
                            error = f"Lỗi làm mới tracking: {e}"
                    
                    # Lấy dữ liệu sau khi refresh
                    if record.tracking_payload:
                        tracking = record.tracking_payload
                        checkpoints = list(reversed(tracking.get('checkpoints') or []))
                        for cp in checkpoints:
                            cp['message'] = _polish_message(cp.get('message'))
                            cp['status_vn'] = _vi_status(cp.get('tag') or cp.get('status'), _polish_message(cp.get('message')))
                        tracking['tag_vn'] = _vi_status(tracking.get('tag') or tracking.get('status'), tracking.get('status'))
                        
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error,
                            "data": tracking or {},
                            "number": number,
                            "slug": slug or "",
                            "checkpoints": checkpoints,
                            "last_update": record.tracking_last_update,
                            "from_cache": False,
                        })
                else:
                    error = f"Đơn {query} chưa có mã vận đơn."
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": query, "slug": "",
                    })
            
            # Bước 4: Nếu không tìm thấy trong database, kiểm tra xem input có phải mã vận đơn trực tiếp không
            if not number and _looks_like_tracking(query):
                # Input là mã vận đơn → gọi API trực tiếp (fallback cũ)
                number = query
                slug = slug_input or _guess_slug(number)
                
                api_key = request.env['ir.config_parameter'].sudo().get_param('aftership.api_key') or ''
                if not api_key:
                    error = "Hệ thống chưa cấu hình API key."
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": query, "slug": slug_input,
                    })
                
                headers = {"Content-Type": "application/json", "as-api-key": api_key}
                
                if slug:
                    url = f"{AFTERSHIP_API_BASE}/trackings/{slug}/{number}?lang=vi"
                    r = requests.get(url, headers=headers, timeout=20)
                    if not r.ok:
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
                
                tracking = (data or {}).get('tracking') or data or {}
                checkpoints = list(reversed(tracking.get('checkpoints') or []))
                for cp in checkpoints:
                    cp['message'] = _polish_message(cp.get('message'))
                    cp['status_vn'] = _vi_status(cp.get('tag') or cp.get('status'), _polish_message(cp.get('message')))
                tracking['tag_vn'] = _vi_status(tracking.get('tag') or tracking.get('status'), tracking.get('status'))
                
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": None,
                    "data": tracking or {},
                    "number": number or query,
                    "slug": slug or slug_input,
                    "checkpoints": checkpoints,
                    "from_cache": False,
                })
            
            # Bước 5: Nếu vẫn không có mã vận đơn, báo lỗi
            if not number:
                error = f"Không tìm thấy mã vận đơn cho: {query}"
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": error, "data": {}, "number": query, "slug": slug_input,
                })

        except Exception as e:
            error = f"Lỗi kết nối: {e}"
            return request.render("hlv_tracking_aftership.website_track_result", {
                "error": error, "data": {}, "number": query, "slug": slug_input,
            })