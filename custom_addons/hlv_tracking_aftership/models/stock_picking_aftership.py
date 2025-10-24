# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = "stock.picking"
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
        """Create tracking on AfterShip once tracking_number is available."""
        for pick in self:
            if not pick.tracking_number:
                raise UserError("Chưa có Tracking Number.")
            slug = pick.tracking_slug or "jtexpress-vn"
            client = pick._aftership_client()
            try:
                res = client.create_tracking(slug, pick.tracking_number, title=pick.name)
            except Exception as e:
    # Lấy body chi tiết nếu có
                import requests
                body = ""
                if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                    body = f"\nResponse: {e.response.text}"
                _logger.exception("AfterShip create tracking failed: %s%s", e, body)
                raise UserError(f"AfterShip lỗi khi tạo tracking: {e}{body}")
            tracking = (res or {}).get("data") or {}
            pick.aftership_id = tracking.get("id")
            pick.tracking_payload = tracking
            pick.action_refresh_tracking_aftership()

    def action_refresh_tracking_aftership(self):
        """Pull latest tracking info from AfterShip (by id if available, else by slug+number)."""
        for pick in self:
            client = pick._aftership_client()
            try:
                if pick.aftership_id:
                    res = client.get_tracking_by_id(pick.aftership_id)
                else:
                    if not (pick.tracking_slug and pick.tracking_number):
                        continue
                    res = client.get_tracking_by_number(pick.tracking_slug, pick.tracking_number)
            except Exception as e:
                _logger.warning("AfterShip refresh failed for %s: %s", pick.name, e)
                continue

            # tracking = (res or {}).get("data", {}).get("tracking") or {}
            tracking = (res or {}).get("data") or {}
            pick.tracking_payload = tracking

            # Normalize status/tag/subtag
            tag = tracking.get("tag") or tracking.get("subtag") or tracking.get("status")
            pick.tracking_status = tag
            
            
            # vi_status = self._vi_label(tracking.get("tag"), tracking.get("subtag_message"), tracking.get("message"))
            # pick.tracking_status = vi_status or tracking.get("tag") or tracking.get("status")


            # Last checkpoint summary
            checkpoints = tracking.get("checkpoints") or []
            cp_text = False
            if checkpoints:
                last = checkpoints[-1]
                cp_text = f"{(last.get('tag') or '')} - {(last.get('message') or '')}"
            pick.tracking_last_checkpoint = cp_text


    def _compute_tracking_timeline(self):
        for p in self:
            tr = p.tracking_payload or {}
            cps = tr.get("checkpoints") or []
            if not cps:
                p.tracking_timeline_html = "<em>Chưa có checkpoint.</em>"
                continue
            items = []
            for cp in reversed(cps):  # mới nhất lên đầu
                t  = cp.get("checkpoint_time") or ""
                tag = cp.get("tag") or ""
                msg = cp.get("message") or ""
                items.append(f"""
                <div class='tl-item'>
                    <div class='tl-dot'></div>
                    <div class='tl-content'>
                    <div class='tl-title'><b>{tag}</b> <small style='opacity:.6'>({t})</small></div>
                    <div class='tl-msg'>{msg}</div>
                    </div>
                </div>
                """)
            p.tracking_timeline_html = """
            <div class='timeline'>%s</div>
            <style>
                .timeline{position:relative;margin:.5rem 0;padding-left:1.25rem;border-left:2px solid #e5e7eb}
                .tl-item{position:relative;margin:0 0 .75rem 0}
                .tl-dot{position:absolute;left:-8px;top:.45rem;width:.75rem;height:.75rem;border-radius:999px;background:#3b82f6}
                .tl-title{margin-bottom:.25rem}
                .tl-msg{color:#374151}
            </style>
            """ % ("\n".join(items))
    @api.model
    def cron_aftership_refresh_all(self):
        picks = self.search([('aftership_id', '!=', False)])
        picks.action_refresh_tracking_aftership()