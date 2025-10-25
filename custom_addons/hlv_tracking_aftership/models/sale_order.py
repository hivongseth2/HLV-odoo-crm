# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


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


class SaleOrder(models.Model):
    _inherit = "sale.order"

    tracking_timeline_html = fields.Html(string="Tracking Timeline", compute="_compute_tracking_timeline", sanitize=False, readonly=True)

    tracking_slug = fields.Char(string="Carrier Slug", default="jtexpress-vn")
    tracking_number = fields.Char(string="Tracking Number")
    aftership_id = fields.Char(string="AfterShip Tracking ID", copy=False, readonly=True)
    tracking_status = fields.Char(string="Tracking Status", copy=False, readonly=True)
    tracking_last_checkpoint = fields.Char(string="Last Checkpoint", copy=False, readonly=True)
    tracking_payload = fields.Json(string="Tracking JSON", copy=False, readonly=True)

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
            order.action_refresh_tracking_aftership()

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

