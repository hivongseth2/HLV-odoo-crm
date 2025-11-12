import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class SalesResponse(models.Model):
    _name = 'hlv.ai.sales.response'
    _description = 'AI Sales Response'
    _rec_name = 'response_id'
    _order = 'create_date desc'

    # Basic Information
    response_id = fields.Char('Response ID', required=True, copy=False, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('hlv.ai.sales.response') or 'New')
    
    # Related Records
    sales_request_id = fields.Many2one('hlv.ai.sales.request', string='Sales Request', 
        required=True, ondelete='cascade')
    
    # Response Details
    response_type = fields.Selection([
        ('quotation', 'Quotation'),
        ('availability', 'Stock Availability'),
        ('supplier_quote', 'Supplier Quotation'),
        ('error', 'Error Response'),
        ('info', 'Information'),
    ], string='Response Type', required=True)
    
    response_text = fields.Text('Response Text', required=True)
    
    # Delivery Information
    delivery_method = fields.Selection([
        ('email', 'Email'),
        ('zalo', 'Zalo Message'),
        ('sms', 'SMS'),
        ('api', 'API Response'),
    ], string='Delivery Method', default='api')
    
    recipient = fields.Char('Recipient', help='Email, phone number, or API endpoint')
    
    # Status
    sent = fields.Boolean('Sent', default=False)
    sent_date = fields.Datetime('Sent Date', readonly=True)
    delivery_status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    ], string='Delivery Status', default='pending')
    
    # Additional Information
    attachments = fields.Text('Attachments', help='JSON list of attachment information')
    metadata = fields.Text('Metadata', help='Additional metadata in JSON format')
    
    @api.model
    def create(self, vals):
        if vals.get('response_id', 'New') == 'New':
            vals['response_id'] = self.env['ir.sequence'].next_by_code('hlv.ai.sales.response') or 'New'
        return super().create(vals)
    
    def action_send_response(self):
        """Send the response to the recipient"""
        self.ensure_one()
        
        try:
            if self.delivery_method == 'email':
                self._send_via_email()
            elif self.delivery_method == 'zalo':
                self._send_via_zalo()
            elif self.delivery_method == 'sms':
                self._send_via_sms()
            elif self.delivery_method == 'api':
                self._send_via_api()
            
            self.write({
                'sent': True,
                'sent_date': fields.Datetime.now(),
                'delivery_status': 'sent'
            })
            
            _logger.info("Response %s sent successfully via %s", self.response_id, self.delivery_method)
            
        except Exception as e:
            _logger.error("Failed to send response %s: %s", self.response_id, str(e))
            self.write({'delivery_status': 'failed'})
            raise
    
    def _send_via_email(self):
        """Send response via email"""
        if not self.recipient:
            raise ValueError("Email recipient not specified")
        
        # Use Odoo's mail system
        mail_values = {
            'subject': f'AI Sales Response - {self.sales_request_id.request_id}',
            'body_html': f'<p>{self.response_text.replace(chr(10), "<br>")}</p>',
            'email_to': self.recipient,
            'email_from': self.env.company.email or 'noreply@example.com',
        }
        
        mail = self.env['mail.mail'].create(mail_values)
        mail.send()
    
    def _send_via_zalo(self):
        """Send response via Zalo"""
        if not self.recipient:
            raise ValueError("Zalo recipient not specified")
        
        # Use the existing Zalo module
        zalo_config = self.env['hlv.zalo.zns'].search([('active', '=', True)], limit=1)
        if not zalo_config:
            raise ValueError("No active Zalo ZNS configuration found")
        
        response = zalo_config.send_zns(
            msisdn=self.recipient,
            params={'message': self.response_text}
        )
        
        return response
    
    def _send_via_sms(self):
        """Send response via SMS"""
        # This would require SMS gateway integration
        # For now, just log the action
        _logger.info("SMS sending not implemented yet for response %s", self.response_id)
        raise NotImplementedError("SMS delivery not implemented")
    
    def _send_via_api(self):
        """Send response via API (webhook or callback)"""
        # This would typically be handled by the API controller
        # For now, just mark as sent
        _logger.info("API response %s ready for delivery", self.response_id)
    
    def action_mark_delivered(self):
        """Mark response as delivered (for external confirmation)"""
        self.ensure_one()
        self.write({'delivery_status': 'delivered'})
    
    def action_retry_send(self):
        """Retry sending the response"""
        self.ensure_one()
        self.write({'delivery_status': 'pending'})
        self.action_send_response()