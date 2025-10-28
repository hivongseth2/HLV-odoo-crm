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
        
        _logger.info(f"🔍 TRACK_SEARCH: Input={query}, Slug={slug_input}")
        
        error = None
        data = {}
        number = None
        slug = slug_input or None
        last_update = None
        api_call_count = 0  # Đếm số lần gọi API

        try:
            # Bước 1: Ưu tiên tìm kiếm trong database theo mã đơn hàng hoặc mã vận đơn
            Picking = request.env["stock.picking"].sudo()
            SaleOrder = request.env["sale.order"].sudo()
            
            pick = None
            order = None
            
            # Tìm trong stock.picking
            pick = Picking.search([
                '|', '|', ('name', '=', query),
                ('origin', '=', query),
                ('tracking_number', '=', query)
            ], limit=1)
            
            # Nếu picking không có, tìm trong sale.order
            if not pick:
                order = SaleOrder.search([
                    '|', '|', ('name', '=', query),
                    ('client_order_ref', '=', query),
                    ('tracking_number', '=', query)
                ], limit=1)
                
                # Nếu tìm thấy order, lấy picking từ order
                if order:
                    pick = order.picking_ids.filtered(lambda p: p.tracking_number)[:1]
            
            # Bước 2: Nếu tìm thấy picking/order và có tracking_payload
            # LUÔN lấy từ database, KHÔNG bao giờ gọi API từ website
            if pick and pick.tracking_payload:
                # Sử dụng dữ liệu từ database (KHÔNG GỌI API)
                _logger.info(f"✅ DB_HIT: Lấy từ database cho picking {pick.name}")
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
            
            # Bước 2b: Nếu có order nhưng chưa có tracking_payload
            if order and order.tracking_payload:
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
            
            # Bước 3: Nếu có picking/order nhưng CHƯA có payload
            # CHỈ đăng ký AfterShip lần đầu, SAU ĐÓ dữ liệu sẽ được cập nhật qua WEBHOOK
            if pick or order:
                record = pick or order
                
                # Kiểm tra có tracking number không
                if not record.tracking_number:
                    error = f"Đơn {query} chưa có mã vận đơn."
                    _logger.warning(f"⚠️  NO_TRACKING: {query} chưa có tracking_number")
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": query, "slug": "",
                    })
                
                number = record.tracking_number
                slug = record.tracking_slug or slug_input
                
                # Nếu chưa đăng ký AfterShip, đăng ký ngay (CHỈ 1 LẦN)
                if not record.aftership_id:
                    try:
                        _logger.info(f"📝 API_CALL: Đăng ký tracking {number} với AfterShip (LẦN ĐẦU)")
                        record.action_register_tracking_aftership()
                        api_call_count += 1  # GỌI API 1 LẦN
                    except Exception as e:
                        error = f"Lỗi đăng ký tracking: {e}"
                        _logger.error(f"❌ REGISTER_ERROR: {e}")
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, "data": {}, "number": number, "slug": slug or "",
                        })
                
                # SAU KHI ĐĂNG KÝ, hiển thị dữ liệu từ database
                # Webhook sẽ tự động cập nhật tracking_payload khi có thay đổi
                if record.tracking_payload:
                    tracking = record.tracking_payload
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
                        "last_update": record.tracking_last_update,
                        "from_cache": False,  # Vừa đăng ký lần đầu
                    })
                else:
                    # Vừa đăng ký nhưng chưa có payload (có thể AfterShip chưa trả về data)
                    error = f"Đã đăng ký tracking {number}, vui lòng đợi vài giây và thử lại."
                    _logger.warning(f"⚠️  NO_PAYLOAD: Đã đăng ký nhưng chưa có payload cho {number}")
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": number, "slug": slug or "",
                    })
            
            # Bước 4: Nếu không tìm thấy trong database, kiểm tra xem input có phải mã vận đơn trực tiếp không
            if _looks_like_tracking(query):
                # Input là mã vận đơn trực tiếp
                number = query
                slug = slug_input or _guess_slug(number)
                
                _logger.info(f"🔍 DIRECT_TRACKING: Input có vẻ là mã vận đơn trực tiếp: {number}")
                
                # Tìm xem có picking/order nào với tracking number này không
                existing_pick = Picking.search([('tracking_number', '=', number)], limit=1)
                if existing_pick:
                    # Đã có trong hệ thống, redirect lại để xử lý
                    _logger.info(f"✅ FOUND: Tìm thấy picking {existing_pick.name} với tracking {number}")
                    if existing_pick.tracking_payload:
                        tracking = existing_pick.tracking_payload
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
                            "last_update": existing_pick.tracking_last_update,
                            "from_cache": True,
                        })
                
                # Nếu chưa có trong hệ thống, báo lỗi yêu cầu nhập mã đơn hàng
                error = f"Vui lòng nhập mã đơn hàng (ví dụ: S00123 hoặc WH/OUT/00001) thay vì mã vận đơn."
                _logger.warning(f"⚠️  DIRECT_TRACKING_NOT_FOUND: {number} chưa có trong hệ thống")
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": error, "data": {}, "number": number, "slug": slug or "",
                })
            
            # Bước 5: Không tìm thấy gì cả
            error = f"Không tìm thấy đơn hàng hoặc mã vận đơn cho: {query}"
            _logger.warning(f"⚠️  NOT_FOUND: Không tìm thấy gì cho {query}")
            return request.render("hlv_tracking_aftership.website_track_result", {
                "error": error, "data": {}, "number": query, "slug": slug_input,
            })

        except Exception as e:
            error = f"Lỗi kết nối: {e}"
            _logger.error(f"❌ ERROR: {error}", exc_info=True)
            return request.render("hlv_tracking_aftership.website_track_result", {
                "error": error, "data": {}, "number": query, "slug": slug_input,
            })