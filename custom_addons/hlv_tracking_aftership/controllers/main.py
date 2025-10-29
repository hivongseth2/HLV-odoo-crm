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


def _call_aftership_api(aftership_id: str, api_key: str) -> dict:
    """
    Gọi API AfterShip để lấy thông tin tracking
    Returns: dict hoặc None nếu lỗi
    """
    try:
        headers = {
            'aftership-api-key': api_key,
            'Content-Type': 'application/json',
        }
        url = f"{AFTERSHIP_API_BASE}/trackings/{aftership_id}"
        
        _logger.info(f"🌐 API_CALL: GET {url}")
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            tracking = data.get('data', {}).get('tracking', {})
            _logger.info(f"✅ API_SUCCESS: Got {len(tracking.get('checkpoints', []))} checkpoints")
            return tracking
        else:
            _logger.error(f"❌ API_ERROR: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        _logger.error(f"❌ API_EXCEPTION: {e}")
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
        number = None
        slug = slug_input or None

        try:
            # Lấy API key từ system parameters
            api_key = request.env['ir.config_parameter'].sudo().get_param('aftership.api_key', '')
            if not api_key:
                error = "Hệ thống chưa cấu hình AfterShip API key. Vui lòng liên hệ quản trị viên."
                _logger.error("❌ NO_API_KEY: aftership.api_key not configured")
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": error, "data": {}, "number": query, "slug": slug_input,
                })
            
            # Bước 1: Tìm kiếm trong database để lấy thông tin tracking
            Picking = request.env["stock.picking"].sudo()
            SaleOrder = request.env["sale.order"].sudo()
            
            found_record = None
            
            # Tìm trong stock.picking
            pick = Picking.search([
                '|', '|', ('name', '=', query),
                ('origin', '=', query),
                ('tracking_number', '=', query)
            ], limit=1)
            
            if pick:
                found_record = pick
                _logger.info(f"✅ FOUND_PICKING: {pick.name} | tracking_number={pick.tracking_number} | aftership_id={pick.aftership_id[:8] if pick.aftership_id else 'None'}")
            else:
                # Nếu picking không có, tìm trong sale.order
                order = SaleOrder.search([
                    '|', '|', ('name', '=', query),
                    ('client_order_ref', '=', query),
                    ('tracking_number', '=', query)
                ], limit=1)
                
                if order:
                    _logger.info(f"✅ FOUND_ORDER: {order.name} | tracking_number={order.tracking_number}")
                    # Ưu tiên lấy picking từ order nếu có
                    pick_from_order = order.picking_ids.filtered(lambda p: p.tracking_number)[:1]
                    if pick_from_order:
                        found_record = pick_from_order
                        _logger.info(f"✅ FOUND_PICKING_FROM_ORDER: {pick_from_order.name}")
                    else:
                        found_record = order
            
            # Bước 2: Nếu tìm thấy record
            if found_record:
                record = found_record
                
                _logger.info(f"🔍 CHECK_RECORD: {record._name} {record.name} | tracking_number={record.tracking_number}")
                
                # Lấy tracking number từ record
                number = record.tracking_number
                slug = record.tracking_slug or slug_input
                
                # Nếu record không có tracking_number → Báo lỗi
                if not number:
                    error = f"Đơn {query} chưa có mã vận đơn."
                    _logger.warning(f"⚠️  NO_TRACKING: {record.name} chưa có tracking_number")
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": query, "slug": "",
                    })
                
                # Nếu chưa đăng ký AfterShip, đăng ký ngay
                if not record.aftership_id:
                    try:
                        _logger.info(f"📝 REGISTERING: Đăng ký tracking {number} với AfterShip")
                        record.action_register_tracking_aftership()
                        request.env.cr.commit()
                        record.invalidate_recordset(['aftership_id'])
                        _logger.info(f"✅ REGISTERED: aftership_id={record.aftership_id[:8] if record.aftership_id else 'None'}")
                    except Exception as e:
                        error = f"Lỗi đăng ký tracking: {e}"
                        _logger.error(f"❌ REGISTER_ERROR: {e}")
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, "data": {}, "number": number, "slug": slug or "",
                        })
                
                # GỌI API AFTERSHIP ĐỂ LẤY DỮ LIỆU MỚI NHẤT
                if record.aftership_id:
                    _logger.info(f"🌐 CALLING_API: Lấy dữ liệu từ AfterShip cho {number}")
                    tracking = _call_aftership_api(record.aftership_id, api_key)
                    
                    if tracking:
                        # Có dữ liệu từ API
                        checkpoints = list(reversed(tracking.get('checkpoints') or []))
                        _logger.info(f"📊 API_CHECKPOINTS: {len(checkpoints)} checkpoints | tag={tracking.get('tag')}")
                        
                        # Xử lý dữ liệu hiển thị
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
                            "last_update": None,  # API data là real-time
                            "from_api": True,  # Flag để biết data từ API
                        })
                    else:
                        # API lỗi hoặc chưa có dữ liệu
                        _logger.warning(f"⚠️  API_NO_DATA: AfterShip chưa có dữ liệu cho {number}")
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": None,
                            "data": {
                                "tracking_number": number,
                                "slug": slug,
                                "tag": "InfoReceived",
                                "tag_vn": "Đã đăng ký theo dõi",
                            },
                            "number": number,
                            "slug": slug or "",
                            "checkpoints": [],
                            "last_update": None,
                            "from_api": True,
                            "no_data_yet": True,
                        })
                else:
                    # Không có aftership_id (đăng ký thất bại)
                    error = f"Không thể đăng ký tracking cho đơn {query}"
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": number, "slug": slug or "",
                    })
            
            # Bước 3: Nếu KHÔNG tìm thấy record nào trong database
            if not found_record and _looks_like_tracking(query):
                # Input là mã vận đơn trực tiếp
                number = query
                slug = slug_input or _guess_slug(number)
                
                _logger.info(f"🔍 DIRECT_TRACKING: Input có vẻ là mã vận đơn trực tiếp: {number}")
                
                # Tìm xem có picking/order nào với tracking number này không
                existing_pick = Picking.search([('tracking_number', '=', number)], limit=1)
                if existing_pick and existing_pick.aftership_id:
                    _logger.info(f"✅ FOUND_EXISTING: Tìm thấy picking {existing_pick.name} với aftership_id")
                    
                    # Gọi API để lấy data
                    tracking = _call_aftership_api(existing_pick.aftership_id, api_key)
                    if tracking:
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
                            "last_update": None,
                            "from_api": True,
                        })
                
                # Nếu chưa có trong hệ thống, báo lỗi
                error = f"Vui lòng nhập mã đơn hàng (ví dụ: S00123 hoặc WH/OUT/00001) thay vì mã vận đơn."
                _logger.warning(f"⚠️  DIRECT_TRACKING_NOT_FOUND: {number} chưa có trong hệ thống")
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": error, "data": {}, "number": number, "slug": slug or "",
                })
            
            # Bước 4: Không tìm thấy gì cả
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