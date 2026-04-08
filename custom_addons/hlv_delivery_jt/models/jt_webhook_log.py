# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import json
import logging
import pytz
from datetime import datetime

_logger = logging.getLogger(__name__)

class JTWebhookLog(models.Model):
    _name = 'jt.webhook.log'
    _description = 'J&T Webhook Log and Queue'
    _order = 'create_date desc'

    payload = fields.Text(string='Payload', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('failed', 'Failed')
    ], string='State', default='draft', index=True)
    
    error_message = fields.Text(string='Error Message', readonly=True)

    def cron_process_webhooks(self, batch_size=100):
        """Called by ir.cron to process pending webhooks."""
        pending_logs = self.search([('state', '=', 'draft')], limit=batch_size, order='create_date asc')
        for log in pending_logs:
            log.process_webhook()

    def process_webhook(self):
        """Rule 4: Execute heavy logic in background."""
        self.ensure_one()
        try:
            data = json.loads(self.payload)
            
            bill_code = data.get('billCode')
            details = data.get('details')

            if not bill_code:
                self.write({'state': 'failed', 'error_message': 'Missing billCode'})
                return

            # Rule 2: Whitelisted search & write
            picking = self.env['stock.picking'].sudo().search([('jt_bill_code', '=', bill_code)], limit=1)
            if not picking:
                self.write({'state': 'failed', 'error_message': f'Picking not found: {bill_code}'})
                return

            if details:
                if isinstance(details, dict):
                    details = [details]
                
                LogModel = self.env['jt.tracking.log'].sudo()
                
                for det in details:
                    scan_time_str = det.get('scanTime')
                    scan_time = False
                    if scan_time_str:
                        try:
                             scan_dt = datetime.strptime(scan_time_str.replace('T', ' '), "%Y-%m-%d %H:%M:%S")
                             local_tz = pytz.timezone('Asia/Ho_Chi_Minh')
                             local_dt = local_tz.localize(scan_dt)
                             utc_dt = local_dt.astimezone(pytz.UTC)
                             scan_time = fields.Datetime.to_string(utc_dt)
                        except Exception:
                             scan_time = fields.Datetime.now()

                    # Duplicate check
                    domain = [
                        ('picking_id', '=', picking.id),
                        ('scan_type_name', '=', det.get('scanTypeName'))
                    ]
                    if scan_time:
                         domain.append(('scan_time', '=', scan_time))
                    
                    exist = LogModel.search(domain, limit=1)
                    
                    if not exist:
                        LogModel.create({
                            'picking_id': picking.id,
                            'scan_time': scan_time,
                            'scan_type_name': det.get('scanTypeName'),
                            'desc': det.get('desc') or det.get('scanTypeName'),
                            'scan_network_name': det.get('scanNetworkName'),
                            'staff_name': det.get('staffName') or det.get('scanByName'),
                            'staff_contact': det.get('staffContact') or det.get('scanByContact'),
                        })
                        
                        # Rule 2: Whitelisted status write via map
                        scan_type_code = det.get('scanTypeCode')
                        try:
                            scan_type_code = int(scan_type_code)
                        except:
                            pass

                        status_map = {
                            103: 'Created', 104: 'Pickup Failure', 105: 'Cancelled',
                            106: 'Picked', 109: 'Transporting', 110: 'Arrived',
                            112: 'Delivering', 113: 'Delivered', 116: 'Returning',
                            117: 'Returned', 121: 'Finish'
                        }
                        
                        new_status = status_map.get(scan_type_code)
                        if new_status:
                             picking.write({'jt_order_status': new_status})

            self.write({'state': 'processed', 'error_message': False})

        except Exception as e:
            self.write({'state': 'failed', 'error_message': str(e)})
            _logger.exception("Error processing J&T Webhook Log %s: %s", self.id, e)
