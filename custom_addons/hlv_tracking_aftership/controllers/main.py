# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import re
import logging

_logger = logging.getLogger(__name__)


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
        number = None
        slug = slug_input or None
        last_update = None

        try:
            # Bước 1: Ưu tiên tìm kiếm trong database theo mã đơn hàng hoặc mã vận đơn
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
                pick.invalidate_recordset(['aftership_id', 'tracking_payload', 'tracking_last_update', 'tracking_status', 'tracking_slug'])
                _logger.info(f"✅ FOUND_PICKING: {pick.name} | tracking_number={pick.tracking_number} | has_payload={bool(pick.tracking_payload)}")
            else:
                # Nếu picking không có, tìm trong sale.order
                order = SaleOrder.search([
                    '|', '|', ('name', '=', query),
                    ('client_order_ref', '=', query),
                    ('tracking_number', '=', query)
                ], limit=1)
                
                if order:
                    order.invalidate_recordset(['aftership_id', 'tracking_payload', 'tracking_last_update', 'tracking_status', 'tracking_slug'])
                    _logger.info(f"✅ FOUND_ORDER: {order.name} | tracking_number={order.tracking_number}")
                    # Ưu tiên lấy picking từ order nếu có
                    pick_from_order = order.picking_ids.filtered(lambda p: p.tracking_number)[:1]
                    if pick_from_order:
                        pick_from_order.invalidate_recordset(['aftership_id', 'tracking_payload', 'tracking_last_update', 'tracking_status', 'tracking_slug'])
                        found_record = pick_from_order
                        _logger.info(f"✅ FOUND_PICKING_FROM_ORDER: {pick_from_order.name}")
                    else:
                        found_record = order
            
            # Bước 2: Nếu tìm thấy record và có tracking_payload
            # LUÔN lấy từ database, KHÔNG bao giờ gọi API từ website
            if found_record and found_record.tracking_payload:
                _logger.info(f"✅ DB_HIT: Lấy từ database cho {found_record._name} {found_record.name}")
                tracking = found_record.tracking_payload
                number = found_record.tracking_number
                slug = found_record.tracking_slug
                last_update = found_record.tracking_last_update
                
                checkpoints = list(reversed(tracking.get('checkpoints') or []))
                _logger.info(f"📊 CHECKPOINTS: {len(checkpoints)} checkpoints | tag={tracking.get('tag')}")
                
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
                    "is_first_time": False,
                })
            
            # Bước 3: Nếu tìm thấy record nhưng CHƯA có payload
            # CHỈ đăng ký AfterShip lần đầu, SAU ĐÓ dữ liệu sẽ được cập nhật qua WEBHOOK
            if found_record:
                record = found_record
                
                _logger.info(f"🔍 CHECK_RECORD: {record._name} {record.name} | tracking_number={record.tracking_number}")
                
                # Lấy tracking number từ record (ĐÃ CÓ SẴN TỪ MISA)
                number = record.tracking_number
                slug = record.tracking_slug or slug_input
                
                # Nếu record không có tracking_number → Báo lỗi
                if not number:
                    error = f"Đơn {query} chưa có mã vận đơn."
                    _logger.warning(f"⚠️  NO_TRACKING: {record.name} chưa có tracking_number")
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": query, "slug": "",
                        "is_first_time": False,
                    })
                
                # Nếu chưa đăng ký AfterShip, đăng ký ngay (CHỈ 1 LẦN)
                if not record.aftership_id:
                    try:
                        _logger.info(f"📝 API_CALL_1: Đăng ký tracking {number} với AfterShip")
                        record.action_register_tracking_aftership()
                        
                        # FLUSH transaction để lưu dữ liệu vào database ngay
                        request.env.cr.commit()
                        _logger.info(f"💾 COMMITTED: Đã lưu aftership_id vào database")
                        
                        # Refresh record để lấy dữ liệu mới nhất sau khi đăng ký
                        record.invalidate_recordset(['aftership_id', 'tracking_payload', 'tracking_last_update', 'tracking_status'])
                        
                        # ============================================================
                        # OPTION 2: Thử làm mới NGAY SAU khi đăng ký (CHỈ 1 LẦN)
                        # Mục đích: Có cơ hội hiển thị dữ liệu ngay lập tức nếu AfterShip đã có
                        # ============================================================
                        try:
                            import time
                            time.sleep(2)  # Đợi 2 giây để AfterShip xử lý
                            
                            _logger.info(f"📝 API_CALL_2: Thử làm mới tracking {number} (optional)")
                            record.action_refresh_tracking_aftership()
                            request.env.cr.commit()
                            record.invalidate_recordset(['tracking_payload'])
                            _logger.info(f"🔄 REFRESHED: has_payload={bool(record.tracking_payload)}")
                        except Exception as refresh_error:
                            # Nếu làm mới thất bại thì không sao, webhook sẽ lo
                            _logger.warning(f"⚠️  REFRESH_FAILED: {refresh_error} (webhook sẽ cập nhật sau)")
                        
                    except Exception as e:
                        error = f"Lỗi đăng ký tracking: {e}"
                        _logger.error(f"❌ REGISTER_ERROR: {e}")
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, "data": {}, "number": number, "slug": slug or "",
                            "is_first_time": False,
                        })
                
                # SAU KHI ĐĂNG KÝ (và có thể đã làm mới), hiển thị dữ liệu
                if record.tracking_payload:
                    # Trường hợp may mắn: Đã có dữ liệu ngay (từ refresh hoặc webhook nhanh)
                    tracking = record.tracking_payload
                    checkpoints = list(reversed(tracking.get('checkpoints') or []))
                    _logger.info(f"📊 CHECKPOINTS: {len(checkpoints)} checkpoints")
                    
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
                        "from_cache": False,
                        "is_first_time": True,  # Vừa đăng ký lần đầu nhưng đã có data
                    })
                else:
                    # ============================================================
                    # OPTION 1: Vừa đăng ký nhưng chưa có payload
                    # Hiển thị thông báo thân thiện cho user
                    # ============================================================
                    _logger.info(f"⏳ FIRST_TIME_NO_DATA: Đã đăng ký nhưng chưa có payload cho {number}")
                    
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
                        "last_update": record.tracking_last_update,
                        "from_cache": False,
                        "is_first_time": True,  # FLAG quan trọng để hiển thị thông báo
                        "no_data_yet": True,    # FLAG để hiển thị hướng dẫn
                    })
            
            # Bước 4: Nếu KHÔNG tìm thấy record nào trong database
            if not found_record and _looks_like_tracking(query):
                number = query
                slug = slug_input or _guess_slug(number)
                
                _logger.info(f"🔍 DIRECT_TRACKING: Input có vẻ là mã vận đơn trực tiếp: {number}")
                
                # Tìm xem có picking/order nào với tracking number này không
                existing_pick = Picking.search([('tracking_number', '=', number)], limit=1)
                if existing_pick:
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
                            "is_first_time": False,
                        })
                
                # Nếu chưa có trong hệ thống, báo lỗi yêu cầu nhập mã đơn hàng
                error = f"Vui lòng nhập mã đơn hàng (ví dụ: S00123 hoặc WH/OUT/00001) thay vì mã vận đơn."
                _logger.warning(f"⚠️  DIRECT_TRACKING_NOT_FOUND: {number} chưa có trong hệ thống")
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": error, "data": {}, "number": number, "slug": slug or "",
                    "is_first_time": False,
                })
            
            # Bước 5: Không tìm thấy gì cả
            error = f"Không tìm thấy đơn hàng hoặc mã vận đơn cho: {query}"
            _logger.warning(f"⚠️  NOT_FOUND: Không tìm thấy gì cho {query}")
            return request.render("hlv_tracking_aftership.website_track_result", {
                "error": error, "data": {}, "number": query, "slug": slug_input,
                "is_first_time": False,
            })

        except Exception as e:
            error = f"Lỗi kết nối: {e}"
            _logger.error(f"❌ ERROR: {error}", exc_info=True)
            return request.render("hlv_tracking_aftership.website_track_result", {
                "error": error, "data": {}, "number": query, "slug": slug_input,
                "is_first_time": False,
            })