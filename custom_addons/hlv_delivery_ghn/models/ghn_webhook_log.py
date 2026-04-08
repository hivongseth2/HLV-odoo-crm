# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import json
import logging

_logger = logging.getLogger(__name__)

class GHNWebhookLog(models.Model):
    _name = 'ghn.webhook.log'
    _description = 'GHN Webhook Log and Queue'
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
            
            order_code = data.get("OrderCode")
            status = data.get("Status")
            
            if not order_code:
                self.write({'state': 'failed', 'error_message': 'Missing OrderCode'})
                return

            # Rule 2: Whitelisted search & write
            picking = self.env['stock.picking'].sudo().search([('ghn_order_code', '=', order_code)], limit=1)
            
            if picking:
                vals = {}
                msg_body = f"GHN Webhook Update ({data.get('Type', 'unknown')}):<br/>"
                
                # Rule 2: Payload Whitelisting
                if status:
                    vals['ghn_order_status'] = status
                    msg_body += f"- Status: {status}<br/>"
                
                if 'TotalFee' in data:
                    vals['ghn_total_fee'] = data.get('TotalFee')
                    msg_body += f"- Total Fee: {data.get('TotalFee')}<br/>"

                if 'CODAmount' in data:
                    vals['ghn_cod_amount'] = data.get('CODAmount')
                    msg_body += f"- COD Amount: {data.get('CODAmount')}<br/>"

                if vals:
                    picking.write(vals)
                    picking.message_post(body=msg_body)
                    
                    # Create Tracking Log
                    status_map = picking._get_ghn_status_map()
                    status_vn = status_map.get(status, status)
                    
                    log_time = fields.Datetime.now()
                    if data.get("Time"):
                        try:
                            t_str = data.get("Time").replace('T', ' ').replace('Z', '').split('.')[0]
                            log_time = fields.Datetime.from_string(t_str)
                        except:
                            pass

                    self.env['ghn.tracking.log'].sudo().create({
                        'picking_id': picking.id,
                        'status_code': status,
                        'status_name': status_vn,
                        'description': data.get('Description') or msg_body,
                        'time_log': log_time,
                        'location': data.get('Warehouse') or ''
                    })
            else:
                self.write({'state': 'failed', 'error_message': f'Picking not found: {order_code}'})
                return

            self.write({'state': 'processed', 'error_message': False})

        except Exception as e:
            self.write({'state': 'failed', 'error_message': str(e)})
            _logger.exception("Error processing GHN Webhook Log %s: %s", self.id, e)
