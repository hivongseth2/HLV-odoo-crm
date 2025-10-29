# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime
from .tracking_utils import guess_carrier_slug, is_valid_tracking_number, should_auto_register_tracking
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


class SaleOrder(models.Model):
    _inherit = "sale.order"

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
        """Auto-detect carrier slug and sync to pickings when creating order."""
        for vals in vals_list:
            tracking_number = vals.get('tracking_number')
            if tracking_number and not vals.get('tracking_slug'):
                # Get customer name for context
                partner_id = vals.get('partner_id')
                customer_name = None
                if partner_id:
                    partner = self.env['res.partner'].browse(partner_id)
                    if partner.exists():
                        customer_name = partner.name
                
                order_ref = vals.get('name') or vals.get('origin')
                slug = guess_carrier_slug(tracking_number, customer_name, order_ref)
                if slug:
                    vals['tracking_slug'] = slug
                    _logger.info(f"Auto-detected carrier slug '{slug}' for order with tracking {tracking_number}")
        
        records = super().create(vals_list)
        
        # Auto-register with AfterShip if enabled
        auto_register_param = self.env['ir.config_parameter'].sudo().get_param('aftership.auto_register', 'false')
        if auto_register_param.lower() == 'true':
            for record in records:
                if should_auto_register_tracking(record.tracking_number, record.tracking_slug):
                    try:
                        record.action_register_tracking_aftership()
                        _logger.info(f"Auto-registered tracking {record.tracking_number} with AfterShip for order {record.name}")
                    except Exception as e:
                        _logger.warning(f"Failed to auto-register tracking for order {record.name}: {e}")
        
        # Sync tracking to related pickings
        for record in records:
            if record.tracking_number or record.tracking_slug:
                record._sync_tracking_to_pickings()
        
        return records
    
    def write(self, vals):
        """Auto-detect carrier slug and sync to pickings when updating tracking."""
        if 'tracking_number' in vals and vals.get('tracking_number'):
            for record in self:
                if not vals.get('tracking_slug') and not record.tracking_slug:
                    customer_name = record.partner_id.name if record.partner_id else None
                    order_ref = record.name
                    
                    slug = guess_carrier_slug(vals['tracking_number'], customer_name, order_ref)
                    if slug:
                        vals['tracking_slug'] = slug
                        _logger.info(f"Auto-detected carrier slug '{slug}' for order {record.name}")
        
        result = super().write(vals)
        
        # Auto-register if tracking number is newly set
        if 'tracking_number' in vals and vals.get('tracking_number'):
            auto_register_param = self.env['ir.config_parameter'].sudo().get_param('aftership.auto_register', 'false')
            if auto_register_param.lower() == 'true':
                for record in self:
                    if not record.aftership_id and should_auto_register_tracking(record.tracking_number, record.tracking_slug):
                        try:
                            record.action_register_tracking_aftership()
                            _logger.info(f"Auto-registered tracking {record.tracking_number} with AfterShip for order {record.name}")
                        except Exception as e:
                            _logger.warning(f"Failed to auto-register tracking for order {record.name}: {e}")
        
        # Sync tracking to pickings if changed
        if 'tracking_number' in vals or 'tracking_slug' in vals:
            for record in self:
                record._sync_tracking_to_pickings()
        
        return result
    
    def _sync_tracking_to_pickings(self):
        """Sync tracking_number and tracking_slug to related pickings."""
        self.ensure_one()
        if not (self.tracking_number or self.tracking_slug):
            return
        
        pickings = self.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
        if not pickings:
            return
        
        update_vals = {}
        if self.tracking_number:
            update_vals['tracking_number'] = self.tracking_number
        if self.tracking_slug:
            update_vals['tracking_slug'] = self.tracking_slug
        
        if update_vals:
            pickings.write(update_vals)
            _logger.info(f"Synced tracking info from order {self.name} to {len(pickings)} picking(s)")

    def _aftership_client(self):
        api_key = self.env['ir.config_parameter'].sudo().get_param('aftership.api_key')
        if not api_key:
            raise UserError("Chưa cấu hình 'aftership.api_key' trong System Parameters.")
        from ..services.aftership_client import AfterShipClient
        return AfterShipClient(api_key)

    def action_register_tracking_aftership(self):
        for order in self:
            if not order.tracking_number:
                raise UserError("Chưa có Tracking Number.")
            slug = order.tracking_slug or "jtexpress-vn"
            client = order._aftership_client()
            try:
                res = client.create_tracking(slug, order.tracking_number, title=order.name)
            except Exception as e:
                import requests
                body = ""
                if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                    body = f"\nResponse: {e.response.text}"
                raise UserError(f"AfterShip lỗi khi tạo tracking: {e}{body}")
            tracking = (res or {}).get("data") or {}
            order.aftership_id = tracking.get("id")
            order.tracking_payload = tracking
            order.tracking_last_update = fields.Datetime.now()
            order.action_refresh_tracking_aftership()
            
            # Đăng ký webhook (chỉ cần 1 lần cho toàn hệ thống)
            order._ensure_webhook_registered()

    def action_refresh_tracking_aftership(self):
        for order in self:
            client = order._aftership_client()
            try:
                if order.aftership_id:
                    res = client.get_tracking_by_id(order.aftership_id)
                else:
                    if not (order.tracking_slug and order.tracking_number):
                        continue
                    res = client.get_tracking_by_number(order.tracking_slug, order.tracking_number)
            except Exception:
                continue

            tracking = (res or {}).get("data") or {}
            order.tracking_payload = tracking
            order.tracking_last_update = fields.Datetime.now()

            tag = tracking.get("tag") or tracking.get("subtag") or tracking.get("status")
            order.tracking_status = _vi_status(tag, tag)

            checkpoints = tracking.get("checkpoints") or []
            cp_text = False
            if checkpoints:
                last = checkpoints[-1]
                cp_text = f"{_vi_status(last.get('tag') or last.get('status'), last.get('message'))} - {_polish_message(last.get('message'))}"
            order.tracking_last_checkpoint = cp_text

    def _compute_tracking_timeline(self):
        for o in self:
            tr = o.tracking_payload or {}
            cps = tr.get("checkpoints") or []
            if not cps:
                o.tracking_timeline_html = "<em>Chưa có thông tin giao hàng.</em>"
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
            o.tracking_timeline_html = """
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

