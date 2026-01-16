# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
import json
import logging
import pytz
from datetime import datetime

_logger = logging.getLogger(__name__)

class JTWebhook(http.Controller):

    @http.route('/jt/webhook/status', type='http', auth='public', methods=['POST'], csrf=False)
    def jt_status_update(self, **post):
        """
        Handle J&T status updates
        Format: X-WWW-FORM-URLENCODED
        Param: bizContent (JSON String)
        """
        try:
            # 1. Get bizContent
            biz_content = post.get('bizContent')
            if not biz_content:
                _logger.warning("J&T Webhook: Missing bizContent")
                return json.dumps({'code': '0', 'msg': 'Missing bizContent'})

            # 2. Parse JSON
            try:
                data = json.loads(biz_content)
            except json.JSONDecodeError:
                _logger.error("J&T Webhook: Invalid JSON in bizContent")
                return json.dumps({'code': '0', 'msg': 'Invalid JSON'})

            _logger.info("J&T Webhook Received: %s", json.dumps(data))

            bill_code = data.get('billCode')
            details = data.get('details')

            if not bill_code:
                return json.dumps({'code': '0', 'msg': 'Missing billCode'})

            # 3. Find Picking
            picking = request.env['stock.picking'].sudo().search([('jt_bill_code', '=', bill_code)], limit=1)
            if not picking:
                _logger.warning("J&T Webhook: Picking not found for billCode %s", bill_code)
                # Return success to acknowledge receipt even if we don't have the order (to stop retries)
                return json.dumps({'code': '1', 'msg': 'success', 'data': None})

            # 4. Process Details (Tracking Logs)
            if details:
                # If details is a list (as per example) or object
                if isinstance(details, dict):
                    details = [details]
                
                LogModel = request.env['jt.tracking.log'].sudo()
                
                # Sort details by scanTime to process in order if needed, but we just append
                # Actually, J&T might send latest first or unsorted.
                
                for det in details:
                    # Parse Time
                    scan_time_str = det.get('scanTime')
                    scan_time = False
                    if scan_time_str:
                        try:
                             # Format: 2024-06-21T13:23:56 or 2024-06-05 15:57:04
                             # Normalize format
                             scan_time_str = scan_time_str.replace('T', ' ')
                             scan_dt = datetime.strptime(scan_time_str, "%Y-%m-%d %H:%M:%S")
                             # Convert to UTC for Odoo storage
                             # Assuming input is Vietnam Time (UTC+7)
                             local_tz = pytz.timezone('Asia/Ho_Chi_Minh')
                             local_dt = local_tz.localize(scan_dt)
                             utc_dt = local_dt.astimezone(pytz.UTC)
                             scan_time = fields.Datetime.to_string(utc_dt)
                        except ValueError:
                            pass

                    # Create Log
                    # Check duplicate based on time + type to avoid spamming logs?
                    # or just create everything.
                    # Let's check duplicate to be safe.
                    exist = LogModel.search([
                        ('picking_id', '=', picking.id),
                        ('scan_time', '=', scan_time),
                        ('scan_type_name', '=', det.get('scanTypeName'))
                    ], limit=1)
                    
                    if not exist:
                        LogModel.create({
                            'picking_id': picking.id,
                            'scan_time': scan_time,
                            'scan_type_name': det.get('scanTypeName'),
                            'desc': det.get('desc') or det.get('scanTypeName'), # Fallback desc
                            'scan_network_name': det.get('scanNetworkName'),
                            'staff_name': det.get('staffName') or det.get('scanByName'),
                            'staff_contact': det.get('staffContact') or det.get('scanByContact'),
                        })
                        
                        # Update Picking Status from the latest log in this batch
                        # Mapped status based on scanTypeCode
                        scan_type_code = det.get('scanTypeCode')
                        status_map = {
                            103: 'Created', # Order Placed
                            104: 'Pickup Failure',
                            105: 'Cancelled',
                            106: 'Picked', # Picked Up
                            109: 'Transporting', # Departure
                            110: 'Arrived', # Arrival
                            112: 'Delivering', # On Delivery
                            113: 'Delivered', # Delivered
                            116: 'Returning',
                            117: 'Returned',
                            121: 'Finish'
                        }
                        
                        new_status = status_map.get(scan_type_code)
                        if new_status:
                             picking.write({'jt_order_status': new_status})
            
            return json.dumps({'code': '1', 'msg': 'success', 'data': None})

        except Exception as e:
            _logger.error("J&T Webhook Error: %s", str(e))
            return json.dumps({'code': '0', 'msg': f'Error: {str(e)}'})
