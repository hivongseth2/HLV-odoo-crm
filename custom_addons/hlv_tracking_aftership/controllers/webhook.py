# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class AfterShipWebhookController(http.Controller):
    @http.route(['/aftership/webhook'], type='json', auth='public', methods=['POST'], csrf=False)
    def aftership_webhook(self, **kwargs):
        """
        Optional webhook receiver.
        Secure this by setting system parameter 'aftership.webhook_token'
        and passing ?token=... in the webhook URL configured in AfterShip.
        """
        token = request.params.get('token') or request.httprequest.args.get('token')
        expected = request.env['ir.config_parameter'].sudo().get_param('aftership.webhook_token')
        if expected and token != expected:
            _logger.warning("AfterShip webhook: invalid token")
            return {"ok": False}

        payload = request.jsonrequest or {}
        tracking = (payload.get("data") or {}).get("tracking") or {}

        Picking = request.env['stock.picking'].sudo()
        domain = []
        if tracking.get("id"):
            domain = ['|', ('aftership_id', '=', tracking.get("id")), ('tracking_number', '=', tracking.get("tracking_number"))]
        elif tracking.get("tracking_number"):
            domain = [('tracking_number', '=', tracking.get("tracking_number"))]

        picks = Picking.search(domain, limit=10)
        for p in picks:
            last_msg = False
            checkpoints = tracking.get("checkpoints") or []
            if checkpoints:
                last = checkpoints[-1]
                last_msg = last.get("message")

            p.write({
                "tracking_payload": tracking,
                "tracking_status": tracking.get("tag") or tracking.get("subtag") or tracking.get("status"),
                "tracking_last_checkpoint": last_msg,
            })
        _logger.info("AfterShip webhook updated %s pickings", len(picks))
        return {"ok": True, "updated": len(picks)}