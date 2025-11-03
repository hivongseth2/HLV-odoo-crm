# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import re
import logging
from datetime import datetime, timedelta, timezone
from pytz import timezone as tz

_logger = logging.getLogger(__name__)

# Timezone Việt Nam (UTC+7)
VN_TZ = tz('Asia/Ho_Chi_Minh')

def _format_datetime_vn(dt):
    """Format datetime theo timezone Việt Nam"""
    if not dt:
        return ""
    try:
        # Nếu dt là naive datetime (không có timezone info), coi nó là UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # Convert to Vietnam timezone
        dt_vn = dt.astimezone(VN_TZ)
        return dt_vn.strftime('%d/%m/%Y %H:%M:%S')
    except Exception as e:
        _logger.warning(f"Error formatting datetime: {e}")
        return str(dt)


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


def _format_datetime(dt_str: str) -> str:
    """
    Format datetime string từ ISO format sang định dạng thân thiện
    Input: 2025-10-28T03:07:40+07:00
    Output: 28/10/2025 03:07
    """
    if not dt_str:
        return ""
    
    try:
        # Parse ISO format datetime
        # Xử lý timezone như +07:00
        if '+' in dt_str:
            dt_part = dt_str.split('+')[0]
        elif dt_str.endswith('Z'):
            dt_part = dt_str[:-1]
        else:
            dt_part = dt_str
        
        # Parse datetime
        dt = datetime.fromisoformat(dt_part)
        
        # Format thân thiện: DD/MM/YYYY HH:MM
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception as e:
        _logger.warning(f"⚠️  FORMAT_DATETIME_ERROR: {dt_str} - {e}")
        # Nếu lỗi, trả về nguyên bản
        return dt_str


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
        # Import AfterShipClient từ services
        from odoo.addons.hlv_tracking_aftership.services.aftership_client import AfterShipClient
        
        client = AfterShipClient(api_key)
        _logger.info(f"🌐 API_CALL: Getting tracking for aftership_id={aftership_id[:8]}...")
        
        # Gọi API giống như backend
        res = client.get_tracking_by_id(aftership_id, lang="vi")
        
        # Parse response giống như backend
        tracking = (res or {}).get("data") or {}
        checkpoints = tracking.get('checkpoints', [])
        
        _logger.info(f"✅ API_SUCCESS: Got {len(checkpoints)} checkpoints | tag={tracking.get('tag')}")
        return tracking
        
    except Exception as e:
        _logger.error(f"❌ API_EXCEPTION: {e}", exc_info=True)
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
            
            # DEBUG: Tìm tất cả các picking và order để kiểm tra
            _logger.info(f"🔍 SEARCHING: query='{query}'")
            
            # Tìm trong stock.picking
            pick = Picking.search([
                '|', '|', ('name', '=', query),
                ('origin', '=', query),
                ('tracking_number', '=', query)
            ], limit=1)
            
            # DEBUG: Nếu không tìm thấy, thử search ilike
            if not pick:
                _logger.warning(f"⚠️  NO_EXACT_MATCH: Trying ilike search...")
                pick = Picking.search([
                    '|', '|', ('name', 'ilike', query),
                    ('origin', 'ilike', query),
                    ('tracking_number', 'ilike', query)
                ], limit=1)
                if pick:
                    _logger.info(f"✅ FOUND_WITH_ILIKE: {pick.name}")
            
            if pick:
                found_record = pick
                _logger.info(f"✅ FOUND_PICKING: name={pick.name} | origin={pick.origin} | tracking_number={pick.tracking_number or 'EMPTY'} | aftership_id={pick.aftership_id[:8] if pick.aftership_id else 'None'}")
            else:
                # Nếu picking không có, tìm trong sale.order
                order = SaleOrder.search([
                    '|', '|', ('name', '=', query),
                    ('client_order_ref', '=', query),
                    ('tracking_number', '=', query)
                ], limit=1)
                
                # DEBUG: Nếu không tìm thấy, thử search ilike
                if not order:
                    _logger.warning(f"⚠️  NO_EXACT_MATCH_ORDER: Trying ilike search...")
                    order = SaleOrder.search([
                        '|', '|', ('name', 'ilike', query),
                        ('client_order_ref', 'ilike', query),
                        ('tracking_number', 'ilike', query)
                    ], limit=1)
                    if order:
                        _logger.info(f"✅ FOUND_ORDER_WITH_ILIKE: {order.name}")
                
                if order:
                    _logger.info(f"✅ FOUND_ORDER: name={order.name} | client_order_ref={order.client_order_ref or 'EMPTY'} | tracking_number={order.tracking_number or 'EMPTY'}")
                    # Ưu tiên lấy picking từ order nếu có
                    pick_from_order = order.picking_ids[:1]  # Lấy picking đầu tiên, không filter theo tracking_number
                    if pick_from_order:
                        found_record = pick_from_order
                        _logger.info(f"✅ FOUND_PICKING_FROM_ORDER: {pick_from_order.name} | tracking_number={pick_from_order.tracking_number or 'EMPTY'}")
                    else:
                        found_record = order
                else:
                    _logger.warning(f"⚠️  NOT_FOUND_IN_DB: No picking or order found for query='{query}'")
            
            # Bước 2: Nếu tìm thấy record
            if found_record:
                record = found_record
                
                _logger.info(f"🔍 CHECK_RECORD: model={record._name} | name={record.name} | tracking_number={record.tracking_number or 'EMPTY'} | aftership_id={record.aftership_id[:8] if record.aftership_id else 'None'}")
                
                # Lấy tracking number từ record
                number = record.tracking_number
                slug = record.tracking_slug or slug_input
                
                # DEBUG: Kiểm tra giá trị thực tế
                _logger.info(f"📊 VALUES: number={number} | type={type(number)} | bool={bool(number)}")
                
                # Nếu record không có tracking_number và là picking
                # Thử lấy tracking_number từ sale_order liên quan
                if not number and record._name == 'stock.picking' and record.origin:
                    sale_order = SaleOrder.search([('name', '=', record.origin)], limit=1)
                    if sale_order and sale_order.tracking_number and sale_order.aftership_id:
                        # Chỉ copy nếu sale_order đã có tracking_number VÀ aftership_id
                        # (tức là đã được đăng ký từ backend)
                        number = sale_order.tracking_number
                        slug = sale_order.tracking_slug or _guess_slug(number)
                        _logger.info(f"💡 FOUND_FROM_SALE_ORDER: Lấy tracking_number={number} từ sale.order {sale_order.name} | aftership_id={sale_order.aftership_id[:8]}")
                        
                        # Copy sang picking để lần sau không cần tìm lại
                        try:
                            record.write({
                                'tracking_number': number,
                                'tracking_slug': slug,
                                'aftership_id': sale_order.aftership_id,
                            })
                            request.env.cr.commit()
                            record.invalidate_recordset(['tracking_number', 'tracking_slug', 'aftership_id'])
                            number = record.tracking_number
                            slug = record.tracking_slug
                            _logger.info(f"� SYNCED_TO_PICKING: Đã đồng bộ tracking vào picking {record.name}")
                        except Exception as sync_error:
                            _logger.warning(f"⚠️  SYNC_FAILED: {sync_error}")
                    else:
                        # Sale order không có tracking hoặc không được đăng ký - báo lỗi
                        if sale_order and not sale_order.tracking_number:
                            error = f"Đơn '{record.name}' chưa có mã vận đơn. Vui lòng cập nhật mã vận đơn trong Odoo."
                        else:
                            error = f"Đơn '{record.name}' chưa có mã vận đơn. Vui lòng cập nhật mã vận đơn trong Odoo."
                        _logger.warning(f"⚠️  NO_TRACKING_FROM_ORDER: {record.name} hoặc sale order không có tracking")
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, 
                            "data": {}, 
                            "number": query, 
                            "slug": "",
                            "order_name": record.name,
                        })
                
                # Nếu vẫn không có tracking_number
                if not number:
                    # Kiểm tra xem query có phải là mã vận đơn không (ví dụ: SPXVN05314648703A)
                    if _looks_like_tracking(query):
                        number = query
                        slug = _guess_slug(number)
                        _logger.info(f"💡 USING_QUERY_AS_TRACKING: Query '{query}' có vẻ là mã vận đơn, sẽ dùng làm tracking number")
                        
                        # KHÔNG đăng ký tự động - chỉ báo lỗi nếu chưa đăng ký
                        # (Tránh spam đạt limit API)
                        error = f"Mã vận đơn '{number}' chưa được đăng ký trên hệ thống. Vui lòng liên hệ quản trị viên để cập nhật."
                        _logger.warning(f"⚠️  TRACKING_NOT_REGISTERED: {number} chưa có trong hệ thống")
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, 
                            "data": {}, 
                            "number": number, 
                            "slug": slug or "",
                        })
                    # Thử lấy từ slug_input (user có thể nhập tracking number vào ô "Hãng vận chuyển")
                    elif slug_input and _looks_like_tracking(slug_input):
                        number = slug_input
                        slug = _guess_slug(number)
                        _logger.info(f"💡 USING_INPUT_AS_TRACKING: Dùng input '{slug_input}' làm tracking number")
                        
                        # KHÔNG đăng ký tự động - chỉ báo lỗi nếu chưa đăng ký
                        error = f"Mã vận đơn '{number}' chưa được đăng ký trên hệ thống. Vui lòng liên hệ quản trị viên để cập nhật."
                        _logger.warning(f"⚠️  TRACKING_NOT_REGISTERED: {number} chưa có trong hệ thống")
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, 
                            "data": {}, 
                            "number": number, 
                            "slug": slug or "",
                        })
                    else:
                        # Thực sự không có tracking number
                        error = f"Đơn '{record.name}' chưa có mã vận đơn. Vui lòng cập nhật mã vận đơn trong Odoo hoặc nhập mã vận đơn vào ô tìm kiếm."
                        _logger.warning(f"⚠️  NO_TRACKING: {record.name} (model={record._name}) tracking_number is empty/false")
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": error, 
                            "data": {}, 
                            "number": query, 
                            "slug": "",
                            "order_name": record.name,  # Hiển thị tên đơn tìm thấy
                        })
                
                # Nếu chưa đăng ký AfterShip, báo lỗi
                # (Chỉ đăng ký thông qua Odoo, không đăng ký trên web để tránh spam)
                if not record.aftership_id:
                    _logger.warning(f"⚠️  NOT_REGISTERED: {record.name} chưa được đăng ký với AfterShip")
                    error = f"Đơn '{record.name}' chưa được đăng ký theo dõi trên hệ thống. Vui lòng liên hệ quản trị viên để cập nhật mã vận đơn."
                    return request.render("hlv_tracking_aftership.website_track_result", {
                        "error": error, "data": {}, "number": number, "slug": slug or "",
                        "order_name": record.name,
                    })
                
                # KIỂM TRA CACHE - CHỈ GỌI API NẾU CẦN
                if record.aftership_id:
                    # Kiểm tra xem có nên refresh từ API không
                    should_refresh = record._should_refresh_tracking()
                    
                    if not should_refresh and record.tracking_payload:
                        # Cache còn valid, dùng data cũ
                        cache_time = _format_datetime_vn(record.tracking_last_update)
                        _logger.info(f"📦 USING_CACHE: {number} | Cached at: {cache_time} | No API call needed")
                        tracking = record.tracking_payload
                    else:
                        # Cache expired hoặc chưa có data, gọi API
                        if record.tracking_last_update:
                            cache_time = _format_datetime_vn(record.tracking_last_update)
                            _logger.info(f"🌐 CALLING_API: {number} | Previous cache: {cache_time} | Fetching fresh data from AfterShip")
                        else:
                            _logger.info(f"🌐 CALLING_API: {number} | No cache exist | Fetching data from AfterShip")
                        
                        tracking = _call_aftership_api(record.aftership_id, api_key)
                        
                        # Lưu vào cache nếu có data
                        if tracking:
                            try:
                                from odoo import fields
                                current_time = fields.Datetime.now()
                                record.write({
                                    'tracking_payload': tracking,
                                    'tracking_last_update': current_time,
                                })
                                request.env.cr.commit()
                                
                                # Log chi tiết thời gian cache
                                save_time = _format_datetime_vn(current_time)
                                cache_duration = int(request.env['ir.config_parameter'].sudo().get_param('aftership.cache_duration', '30'))
                                cache_until = current_time + timedelta(minutes=cache_duration)
                                until_time = _format_datetime_vn(cache_until)
                                
                                _logger.info(f"💾 CACHE_SAVED: {number} | Saved at: {save_time} | Expires at: {until_time} ({cache_duration}min)")
                            except Exception as e:
                                _logger.warning(f"⚠️  CACHE_SAVE_FAILED: {number} | Error: {e}")
                    
                    if tracking:
                        # Có dữ liệu từ API
                        checkpoints = list(reversed(tracking.get('checkpoints') or []))
                        _logger.info(f"📊 API_CHECKPOINTS: {len(checkpoints)} checkpoints | tag={tracking.get('tag')}")
                        
                        # Xử lý dữ liệu hiển thị
                        for cp in checkpoints:
                            cp['message'] = _polish_message(cp.get('message'))
                            cp['status_vn'] = _vi_status(cp.get('tag') or cp.get('status'), _polish_message(cp.get('message')))
                            # Format thời gian
                            checkpoint_time = cp.get('checkpoint_time') or cp.get('date_time')
                            if checkpoint_time:
                                cp['formatted_time'] = _format_datetime(checkpoint_time)
                        tracking['tag_vn'] = _vi_status(tracking.get('tag') or tracking.get('status'), tracking.get('status'))
                        
                        # Lấy sale_order_id từ record
                        sale_order_id = None
                        if record._name == 'stock.picking' and record.sale_id:
                            sale_order_id = record.sale_id.id
                        elif record._name == 'sale.order':
                            sale_order_id = record.id
                        
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": None,
                            "data": tracking or {},
                            "number": number,
                            "slug": slug or "",
                            "checkpoints": checkpoints,
                            "sale_order_id": sale_order_id,
                        })
                    else:
                        # API lỗi hoặc chưa có dữ liệu
                        _logger.warning(f"⚠️  API_NO_DATA: AfterShip chưa có dữ liệu cho {number}")
                        
                        # Lấy sale_order_id từ record
                        sale_order_id = None
                        if record._name == 'stock.picking' and record.sale_id:
                            sale_order_id = record.sale_id.id
                        elif record._name == 'sale.order':
                            sale_order_id = record.id
                        
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
                            "no_data_yet": True,
                            "sale_order_id": sale_order_id,
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
                            # Format thời gian
                            checkpoint_time = cp.get('checkpoint_time') or cp.get('date_time')
                            if checkpoint_time:
                                cp['formatted_time'] = _format_datetime(checkpoint_time)
                        tracking['tag_vn'] = _vi_status(tracking.get('tag') or tracking.get('status'), tracking.get('status'))
                        
                        # Lấy sale_order_id từ picking
                        sale_order_id = existing_pick.sale_id.id if existing_pick.sale_id else None
                        
                        return request.render("hlv_tracking_aftership.website_track_result", {
                            "error": None,
                            "data": tracking or {},
                            "number": number,
                            "slug": slug or "",
                            "checkpoints": checkpoints,
                            "last_update": None,
                            "from_api": True,
                            "sale_order_id": sale_order_id,
                        })
                
                # Nếu chưa có trong hệ thống, báo lỗi
                error = f"Mã vận đơn '{number}' chưa được đăng ký trên hệ thống. Vui lòng liên hệ quản trị viên để cập nhật."
                _logger.warning(f"⚠️  DIRECT_TRACKING_NOT_FOUND: {number} chưa có trong hệ thống")
                return request.render("hlv_tracking_aftership.website_track_result", {
                    "error": error, "data": {}, "number": number, "slug": slug or "",
                })
            
            # Bước 4: Không tìm thấy gì cả
            if not found_record:
                error = f"Không tìm thấy đơn hàng cho: {query}. Vui lòng nhập mã đơn hàng hoặc mã vận đơn."
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