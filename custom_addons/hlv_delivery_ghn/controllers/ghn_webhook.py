# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class GHNWebhook(http.Controller):

    @http.route('/ghn/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def ghn_webhook_listener(self, **post):
        """
        Listen to GHN order status updates.
        Payload example:
        {
            "OrderCode": "Z82BS",
            "Status": "ready_to_pick",
            "Type": "create",
            "TotalFee": 71400,
            "CODAmount": 3000000,
            ...
        }
        """
        try:
            # Data from JSON body is automatically parsed into 'post' or request.jsonrequest
            data = request.jsonrequest
            _logger.info("GHN Webhook received data: %s", data)

            if not data:
                return {"code": 200, "message": "No data received"}

            order_code = data.get("OrderCode")
            status = data.get("Status")
            
            if not order_code:
                return {"code": 200, "message": "Missing OrderCode"}

            # Search for the picking with this GHN Order Code
            # Use sudo() to bypass access rights since this is a public endpoint
            picking = request.env['stock.picking'].sudo().search([('ghn_order_code', '=', order_code)], limit=1)
            
            if picking:
                vals = {}
                msg_body = f"GHN Webhook Update ({data.get('Type', 'unknown')}):<br/>"
                
                if status:
                    vals['ghn_order_status'] = status
                    msg_body += f"- Status: {status}<br/>"
                
                if 'TotalFee' in data:
                    vals['ghn_total_fee'] = data.get('TotalFee')
                    msg_body += f"- Total Fee: {data.get('TotalFee')}<br/>"

                if 'CODAmount' in data:
                    vals['ghn_cod_amount'] = data.get('CODAmount')
                    msg_body += f"- COD Amount: {data.get('CODAmount')}<br/>"

                # Update picking
                if vals:
                    picking.write(vals)
                    # Log chatter
                    picking.message_post(body=msg_body)
                    
                    # Create Tracking Log
                    status_map = picking._get_ghn_status_map()
                    status_vn = status_map.get(status, status)
                    
                    # Parse Time "2021-11-11T03:52:50.158Z"
                    log_time = fields.Datetime.now()
                    if data.get("Time"):
                        try:
                            # Simple cleanup for ISO format
                            t_str = data.get("Time").replace('T', ' ').replace('Z', '').split('.')[0]
                            log_time = fields.Datetime.from_string(t_str)
                        except:
                            pass

                    request.env['ghn.tracking.log'].sudo().create({
                        'picking_id': picking.id,
                        'status_code': status,
                        'status_name': status_vn,
                        'description': data.get('Description') or msg_body,
                        'time_log': log_time,
                        'location': data.get('Warehouse') or ''
                    })
                    
                    _logger.info("GHN Webhook updated picking %s status to %s", picking.name, status)
                else:
                    _logger.info("GHN Webhook received for %s but no relevant fields to update.", picking.name)
            else:
                _logger.warning("GHN Webhook: OrderCode %s not found in system.", order_code)

            # Always return 200 to acknowledge receipt and stop retries
            return {"code": 200, "message": "Success"}

        except Exception as e:
            _logger.exception("GHN Webhook Exception: %s", e)
            # Return 200 even on error to prevent GHN from retrying indefinitely if it's a logic error
            return {"code": 200, "message": "Error processed"}
