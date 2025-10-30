# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging
from datetime import datetime, timedelta, timezone
from pytz import timezone as tz
from .tracking_utils import guess_carrier_slug, is_valid_tracking_number, should_auto_register_tracking

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
    ("Thứ tự", "Đơn hàng"),
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


class StockPicking(models.Model):
    _inherit = "stock.picking"

    tracking_timeline_html = fields.Html(string="Tracking Timeline", compute="_compute_tracking_timeline", sanitize=False, readonly=True)

    tracking_slug = fields.Char(string="Carrier Slug")
    tracking_number = fields.Char(string="Tracking Number")
    aftership_id = fields.Char(string="AfterShip Tracking ID", copy=False, readonly=True)
    tracking_status = fields.Char(string="Tracking Status", copy=False, readonly=True)
    tracking_last_checkpoint = fields.Char(string="Last Checkpoint", copy=False, readonly=True)
    tracking_payload = fields.Json(string="Tracking JSON", copy=False, readonly=True)
    tracking_last_update = fields.Datetime(string="Last Tracking Update", copy=False, readonly=True)
    webhook_registered = fields.Boolean(string="Webhook Registered", default=False, copy=False)
    
    @api.model_create_multi
    def create(self, vals_list):
        """Auto-detect carrier slug when creating picking with tracking number."""
        for vals in vals_list:
            tracking_number = vals.get('tracking_number')
            if tracking_number and not vals.get('tracking_slug'):
                # Try to detect carrier from context
                customer_name = None
                order_ref = vals.get('origin')
                
                # If we have sale_id, get customer name
                if vals.get('sale_id'):
                    sale = self.env['sale.order'].browse(vals['sale_id'])
                    if sale.exists():
                        customer_name = sale.partner_id.name
                        order_ref = sale.name
                
                slug = guess_carrier_slug(tracking_number, customer_name, order_ref)
                if slug:
                    vals['tracking_slug'] = slug
                    _logger.info(f"Auto-detected carrier slug '{slug}' for picking with tracking {tracking_number}")
        
        records = super().create(vals_list)
        
        # Auto-register with AfterShip if enabled
        auto_register_param = self.env['ir.config_parameter'].sudo().get_param('aftership.auto_register', 'false')
        if auto_register_param.lower() == 'true':
            for record in records:
                if should_auto_register_tracking(record.tracking_number, record.tracking_slug):
                    try:
                        record.action_register_tracking_aftership()
                        _logger.info(f"Auto-registered tracking {record.tracking_number} with AfterShip")
                    except Exception as e:
                        _logger.warning(f"Failed to auto-register tracking for {record.name}: {e}")
        
        return records
    
    def write(self, vals):
        """Auto-detect carrier slug when updating tracking number."""
        if 'tracking_number' in vals and vals.get('tracking_number'):
            for record in self:
                if not vals.get('tracking_slug') and not record.tracking_slug:
                    customer_name = record.sale_id.partner_id.name if record.sale_id else None
                    order_ref = record.origin or record.name
                    
                    slug = guess_carrier_slug(vals['tracking_number'], customer_name, order_ref)
                    if slug:
                        vals['tracking_slug'] = slug
                        _logger.info(f"Auto-detected carrier slug '{slug}' for picking {record.name}")
        
        result = super().write(vals)
        
        # Auto-register if tracking number is newly set
        if 'tracking_number' in vals and vals.get('tracking_number'):
            auto_register_param = self.env['ir.config_parameter'].sudo().get_param('aftership.auto_register', 'false')
            if auto_register_param.lower() == 'true':
                for record in self:
                    if not record.aftership_id and should_auto_register_tracking(record.tracking_number, record.tracking_slug):
                        try:
                            record.action_register_tracking_aftership()
                            _logger.info(f"Auto-registered tracking {record.tracking_number} with AfterShip")
                        except Exception as e:
                            _logger.warning(f"Failed to auto-register tracking for {record.name}: {e}")
        
        return result

    def _aftership_client(self):
        api_key = self.env['ir.config_parameter'].sudo().get_param('aftership.api_key')
        if not api_key:
            raise UserError("Chưa cấu hình 'aftership.api_key' trong System Parameters.")
        from ..services.aftership_client import AfterShipClient
        return AfterShipClient(api_key)

    def action_register_tracking_aftership(self):
        for pick in self:
            if not pick.tracking_number:
                raise UserError("Chưa có Tracking Number.")
            slug = pick.tracking_slug or "jtexpress-vn"
            client = pick._aftership_client()
            try:
                res = client.create_tracking(slug, pick.tracking_number, title=pick.name)
            except Exception as e:
                import requests
                body = ""
                if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                    body = f"\nResponse: {e.response.text}"
                _logger.exception("AfterShip create tracking failed: %s%s", e, body)
                raise UserError(f"AfterShip lỗi khi tạo tracking: {e}{body}")
            tracking = (res or {}).get("data") or {}
            pick.aftership_id = tracking.get("id")
            pick.tracking_payload = tracking
            pick.tracking_last_update = fields.Datetime.now()
            pick.action_refresh_tracking_aftership()
            
            # Đăng ký webhook (chỉ cần 1 lần cho toàn hệ thống)
            pick._ensure_webhook_registered()

    def _should_refresh_tracking(self):
        """
        Kiểm tra xem có cần refresh tracking từ API hay không.
        Sử dụng cache để giảm số lượng API calls.
        
        Returns:
            bool: True nếu cần refresh, False nếu cache còn valid
        """
        self.ensure_one()
        
        # Nếu chưa có data, phải refresh
        if not self.tracking_payload or not self.tracking_last_update:
            _logger.info(f"🔄 NO_CACHE: {self.name} - no cached data, need to fetch from API")
            return True
        
        # Nếu đã delivered, không cần refresh nữa
        delivered_statuses = ['Đã giao thành công', 'Đơn hàng đã được hoàn về']
        if self.tracking_status in delivered_statuses:
            _logger.info(f"🚫 FINAL_STATE: {self.name} already delivered, no refresh needed")
            return False
        
        # Lấy cache duration từ system parameter (mặc định 30 phút)
        cache_minutes = int(
            self.env['ir.config_parameter'].sudo()
            .get_param('aftership.cache_duration', '30')
        )
        
        # Tính thời gian cache hết hạn
        cache_until = self.tracking_last_update + timedelta(minutes=cache_minutes)
        now = fields.Datetime.now()
        
        if now < cache_until:
            remaining_seconds = (cache_until - now).total_seconds()
            remaining_minutes = remaining_seconds / 60
            # Format thời gian cache hết hạn theo VN timezone
            last_update_vn = _format_datetime_vn(self.tracking_last_update)
            cache_until_vn = _format_datetime_vn(cache_until)
            _logger.info(f"📦 CACHE_VALID: {self.name} | Last updated: {last_update_vn} | Cache expires at: {cache_until_vn} | Remaining: {remaining_minutes:.1f} minutes")
            return False
        
        # Format thời gian theo VN timezone
        last_update_vn = _format_datetime_vn(self.tracking_last_update)
        _logger.info(f"⏰ CACHE_EXPIRED: {self.name} | Last updated: {last_update_vn} | Needs refresh")
        return True

    def action_refresh_tracking_aftership(self, force=False):
        """
        Refresh tracking từ AfterShip API.
        
        Args:
            force (bool): Nếu True, bỏ qua cache và luôn refresh
        """
        for pick in self:
            # Kiểm tra cache trước khi gọi API (trừ khi force=True)
            if not force and not pick._should_refresh_tracking():
                _logger.info(f"📦 USING_CACHE: Skipping API call for {pick.name} (cache still valid)")
                continue
            
            client = pick._aftership_client()
            try:
                _logger.info(f"🌐 API_CALL: Refreshing tracking for {pick.name}")
                if pick.aftership_id:
                    res = client.get_tracking_by_id(pick.aftership_id)
                else:
                    if not (pick.tracking_slug and pick.tracking_number):
                        continue
                    res = client.get_tracking_by_number(pick.tracking_slug, pick.tracking_number)
            except Exception as e:
                _logger.warning("AfterShip refresh failed for %s: %s", pick.name, e)
                continue

            tracking = (res or {}).get("data") or {}
            pick.tracking_payload = tracking
            pick.tracking_last_update = fields.Datetime.now()

            tag = tracking.get("tag") or tracking.get("subtag") or tracking.get("status")
            pick.tracking_status = _vi_status(tag, tag)

            checkpoints = tracking.get("checkpoints") or []
            cp_text = False
            if checkpoints:
                last = checkpoints[-1]
                cp_text = f"{_vi_status(last.get('tag') or last.get('status'), last.get('message'))} - {_polish_message(last.get('message'))}"
            pick.tracking_last_checkpoint = cp_text
            
            # Log chi tiết thời gian lưu cache theo VN timezone
            update_time_vn = _format_datetime_vn(pick.tracking_last_update)
            cache_minutes = int(self.env['ir.config_parameter'].sudo().get_param('aftership.cache_duration', '30'))
            cache_until = pick.tracking_last_update + timedelta(minutes=cache_minutes)
            cache_until_vn = _format_datetime_vn(cache_until)
            
            _logger.info(f"✅ CACHE_SAVED: {pick.name} | Time: {update_time_vn} | Duration: {cache_minutes}min | Expires: {cache_until_vn} | Status: {pick.tracking_status}")

    def _compute_tracking_timeline(self):
        for p in self:
            tr = p.tracking_payload or {}
            cps = tr.get("checkpoints") or []
            if not cps:
                p.tracking_timeline_html = "<em>Chưa có thông tin giao hàng.</em>"
                continue
            items = []
            for cp in reversed(cps):
                t = cp.get("checkpoint_time") or cp.get("date_time") or ""
                # Format thời gian sang DD/MM/YYYY HH:MM
                if t:
                    t = _format_datetime(t)
                tag = _vi_status(cp.get("tag") or cp.get("status"), cp.get("status"))
                msg = _polish_message(cp.get("message"))
                location = cp.get("location") or cp.get("city") or ""
                location_html = f"<span class='tl-location'>{location}</span>" if location else ""
                items.append(f"""
                <div class='tl-item'>
                    <div class='tl-marker'>
                        <div class='tl-dot'></div>
                    </div>
                    <div class='tl-content'>
                        <div class='tl-header'>
                            <span class='tl-status'>{tag}</span>
                            <span class='tl-time'>{t}</span>
                        </div>
                        <div class='tl-msg'>{msg}{location_html}</div>
                    </div>
                </div>
                """)
            p.tracking_timeline_html = """
            <div class='hlv-timeline'>%s</div>
            <style>
                .hlv-timeline{position:relative;padding-left:1.5rem;display:flex;flex-direction:column;gap:1rem}
                .hlv-timeline:before{content:"";position:absolute;left:0.5rem;top:0;bottom:0;width:2px;background:linear-gradient(180deg,#60a5fa,#2563eb)}
                .tl-item{display:flex;gap:1rem;position:relative}
                .tl-marker{position:relative;width:1rem;flex:0 0 1rem;display:flex;justify-content:center}
                .tl-dot{width:0.75rem;height:0.75rem;border-radius:50%%;background:#2563eb;box-shadow:0 0 0 4px rgba(37,99,235,0.15)}
                .tl-content{flex:1;background:#f9fafb;border-radius:0.75rem;padding:0.75rem 1rem;box-shadow:0 2px 6px rgba(15,23,42,0.08)}
                .tl-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:0.25rem;font-weight:600;color:#1f2937}
                .tl-time{font-size:0.8rem;color:#6b7280;font-weight:500}
                .tl-msg{color:#374151;font-size:0.95rem;line-height:1.4}
                .tl-location{display:block;font-size:0.8rem;color:#2563eb;margin-top:0.2rem}
                @media (max-width:576px){
                    .hlv-timeline{padding-left:1rem}
                    .tl-content{padding:0.75rem}
                    .tl-header{flex-direction:column;align-items:flex-start;gap:0.25rem}
                    .tl-time{font-size:0.75rem}
                }
            </style>
            """ % ("\n".join(items))

    def _ensure_webhook_registered(self):
        """
        Đảm bảo webhook đã được đăng ký với AfterShip.
        Chỉ cần đăng ký 1 lần cho toàn hệ thống.
        
        Để kích hoạt:
        1. Cấu hình 'aftership.api_key' trong System Parameters
        2. Cấu hình 'aftership.webhook_enabled' = 'true' (optional, mặc định là false)
        3. Cấu hình 'aftership.webhook_secret' (optional, để verify webhook)
        """
        self.ensure_one()
        
        # Kiểm tra xem webhook đã được đăng ký chưa
        webhook_enabled = self.env['ir.config_parameter'].sudo().get_param('aftership.webhook_enabled', 'false')
        if webhook_enabled.lower() != 'true':
            _logger.info("AfterShip webhook is disabled. Set 'aftership.webhook_enabled' = 'true' to enable.")
            return
        
        # Kiểm tra xem đã đăng ký webhook chưa (dùng ir.config_parameter làm flag)
        webhook_registered = self.env['ir.config_parameter'].sudo().get_param('aftership.webhook_registered', 'false')
        if webhook_registered.lower() == 'true':
            _logger.debug("AfterShip webhook already registered")
            return
        
        try:
            # Lấy base URL của hệ thống
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            if not base_url:
                _logger.warning("Cannot register webhook: 'web.base.url' not configured")
                return
            
            webhook_url = f"{base_url}/aftership/webhook"
            
            # Đăng ký webhook
            client = self._aftership_client()
            result = client.register_webhook(webhook_url)
            
            # Đánh dấu đã đăng ký
            self.env['ir.config_parameter'].sudo().set_param('aftership.webhook_registered', 'true')
            _logger.info(f"AfterShip webhook registered successfully: {webhook_url}")
            
        except Exception as e:
            _logger.warning(f"Failed to register AfterShip webhook: {e}")
            # Không raise error vì webhook không phải là critical
