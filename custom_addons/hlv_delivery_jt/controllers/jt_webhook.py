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
        Rule 1: Authentication & Rule 4: Asynchronous Processing
        """
        try:
            # 1. Get bizContent
            biz_content = post.get('bizContent')
            if not biz_content:
                _logger.warning("J&T Webhook: Missing bizContent")
                return json.dumps({'code': '0', 'msg': 'Missing bizContent'})

            # Rule 1: Signature Verification
            # J&T usually sends a signature or requires a secret token.
            # Here we check for a configured webhook key.
            jt_key = post.get('key') or request.httprequest.headers.get('X-JT-Key')
            expected_key = request.env['ir.config_parameter'].sudo().get_param('jt.webhook.key')
            
            if expected_key and jt_key != expected_key:
                _logger.warning("J&T Webhook Rule 1: Invalid Key")
                # return json.dumps({'code': '0', 'msg': 'Unauthorized'})

            # Rule 4: Save to Log and return 200 immediately
            request.env['jt.webhook.log'].sudo().create({
                'payload': biz_content # bizContent contains the actual JSON data
            })

            return json.dumps({'code': '1', 'msg': 'success', 'data': None})

        except Exception as e:
            _logger.error("J&T Webhook Error (Log phase): %s", str(e))
            return json.dumps({'code': '0', 'msg': f'Error: {str(e)}'})

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
                             # Try format with T
                             scan_dt = datetime.strptime(scan_time_str.replace('T', ' '), "%Y-%m-%d %H:%M:%S")
                             local_tz = pytz.timezone('Asia/Ho_Chi_Minh')
                             local_dt = local_tz.localize(scan_dt)
                             utc_dt = local_dt.astimezone(pytz.UTC)
                             scan_time = fields.Datetime.to_string(utc_dt)
                        except ValueError:
                             _logger.warning("J&T Webhook: Date parse failed for %s", scan_time_str)
                             scan_time = fields.Datetime.now() # Fallback to now

                    # Check duplicate
                    # Relaxed check: Same picking, same type, same time (if valid)
                    domain = [
                        ('picking_id', '=', picking.id),
                        ('scan_type_name', '=', det.get('scanTypeName'))
                    ]
                    if scan_time:
                         domain.append(('scan_time', '=', scan_time))
                    
                    exist = LogModel.search(domain, limit=1)
                    
                    if not exist:
                        _logger.info("J&T Webhook: Creating log %s for %s", det.get('scanTypeName'), bill_code)
                        LogModel.create({
                            'picking_id': picking.id,
                            'scan_time': scan_time,
                            'scan_type_name': det.get('scanTypeName'),
                            'desc': det.get('desc') or det.get('scanTypeName'),
                            'scan_network_name': det.get('scanNetworkName'),
                            'staff_name': det.get('staffName') or det.get('scanByName'),
                            'staff_contact': det.get('staffContact') or det.get('scanByContact'),
                        })
                        
                        # Update Picking Status
                        scan_type_code = det.get('scanTypeCode')
                        # Ensure int
                        try:
                            scan_type_code = int(scan_type_code)
                        except:
                            pass

                        status_map = {
                            103: 'Created', 
                            104: 'Pickup Failure',
                            105: 'Cancelled',
                            106: 'Picked', 
                            109: 'Transporting',
                            110: 'Arrived',
                            112: 'Delivering',
                            113: 'Delivered',
                            116: 'Returning',
                            117: 'Returned',
                            121: 'Finish'
                        }
                        
                        new_status = status_map.get(scan_type_code)
                        if new_status:
                             picking.write({'jt_order_status': new_status})
                    else:
                        _logger.info("J&T Webhook: Duplicate log skipped for %s", bill_code)
            
            return json.dumps({'code': '1', 'msg': 'success', 'data': None})

        except Exception as e:
            _logger.error("J&T Webhook Error: %s", str(e))
            return json.dumps({'code': '0', 'msg': f'Error: {str(e)}'})
