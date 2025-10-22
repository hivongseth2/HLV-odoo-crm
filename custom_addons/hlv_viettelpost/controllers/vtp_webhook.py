import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class VTPWebhook(http.Controller):

    @http.route(['/vtp/webhook'], type='json', auth='public', methods=['POST'], csrf=False)
    def vtp_webhook(self, **kwargs):
        payload = request.jsonrequest or {}
        order_no = payload.get("ORDER_NUMBER") or payload.get("ORDER_NUMBER_VTP")
        status = payload.get("STATUS") or payload.get("ORDER_STATUS")
        picking = request.env["stock.picking"].sudo().search([("carrier_tracking_ref", "=", order_no)], limit=1)
        if picking:
            picking.message_post(body=f"Webhook VTP: {status} / {payload.get('STATUS_NAME')}")
        else:
            _logger.info("VTP Webhook: not found %s", order_no)
        return {"ok": True}
