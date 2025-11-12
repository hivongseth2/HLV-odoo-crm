import logging
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ProductInquiry(models.Model):
    _name = 'hlv.ai.product.inquiry'
    _description = 'AI Product Inquiry to Suppliers'
    _rec_name = 'inquiry_id'
    _order = 'create_date desc'

    # Basic Information
    inquiry_id = fields.Char('Inquiry ID', required=True, copy=False, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('hlv.ai.product.inquiry') or 'New')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent to Supplier'),
        ('responded', 'Supplier Responded'),
        ('timeout', 'Response Timeout'),
        ('error', 'Error'),
    ], string='Status', default='draft', tracking=True)
    
    # Related Records
    sales_request_id = fields.Many2one('hlv.ai.sales.request', string='Sales Request', 
        required=True, ondelete='cascade')
    supplier_id = fields.Many2one('hlv.ai.supplier.contact', string='Supplier', 
        required=True, ondelete='cascade')
    
    # Product Information
    product_name = fields.Char('Product Name', required=True)
    description = fields.Text('Product Description')
    quantity = fields.Float('Quantity', required=True)
    unit = fields.Char('Unit', required=True)
    
    # Inquiry Details
    inquiry_message = fields.Text('Inquiry Message', readonly=True)
    sent_date = fields.Datetime('Sent Date', readonly=True)
    expected_response_date = fields.Datetime('Expected Response Date', readonly=True)
    
    # Supplier Response
    response_received_date = fields.Datetime('Response Received Date', readonly=True)
    supplier_response = fields.Text('Supplier Response')
    
    # Pricing Information (parsed from response)
    quoted_price = fields.Float('Quoted Price')
    quoted_currency = fields.Char('Quoted Currency')
    delivery_time = fields.Char('Delivery Time')
    minimum_order_qty = fields.Float('Minimum Order Quantity')
    
    # Additional Information
    supplier_notes = fields.Text('Supplier Notes')
    internal_notes = fields.Text('Internal Notes')
    
    # Communication Details
    zalo_message_id = fields.Char('Zalo Message ID', readonly=True)
    communication_log = fields.Text('Communication Log', readonly=True)
    
    # Status Tracking
    retry_count = fields.Integer('Retry Count', default=0)
    last_retry_date = fields.Datetime('Last Retry Date')
    
    @api.model
    def create(self, vals):
        if vals.get('inquiry_id', 'New') == 'New':
            vals['inquiry_id'] = self.env['ir.sequence'].next_by_code('hlv.ai.product.inquiry') or 'New'
        return super().create(vals)
    
    def action_send_inquiry(self):
        """Send inquiry to supplier via Zalo"""
        self.ensure_one()
        
        try:
            # Generate inquiry message
            ai_config = self.env['hlv.ai.sales.config'].get_default_config()
            message = ai_config.supplier_inquiry_prompt.format(
                product_name=self.product_name,
                description=self.description or 'N/A',
                quantity=self.quantity,
                unit=self.unit
            )
            
            # Send via Zalo
            response = self.supplier_id.send_inquiry_message(
                self.product_name, 
                self.description, 
                self.quantity, 
                self.unit
            )
            
            # Calculate expected response date
            expected_date = datetime.now() + timedelta(hours=self.supplier_id.response_time_hours)
            
            # Update inquiry record
            self.write({
                'state': 'sent',
                'inquiry_message': message,
                'sent_date': fields.Datetime.now(),
                'expected_response_date': expected_date,
                'zalo_message_id': response.get('message_id') if isinstance(response, dict) else None,
                'communication_log': f"Sent at {fields.Datetime.now()}: {message}\n\nZalo Response: {response}"
            })
            
            # Schedule timeout check
            self._schedule_timeout_check()
            
            _logger.info("Inquiry %s sent to supplier %s", self.inquiry_id, self.supplier_id.name)
            
        except Exception as e:
            _logger.error("Failed to send inquiry %s: %s", self.inquiry_id, str(e))
            self.write({
                'state': 'error',
                'communication_log': f"Error at {fields.Datetime.now()}: {str(e)}"
            })
            raise UserError(_("Failed to send inquiry: %s") % str(e))
    
    def action_receive_response(self, response_text, sender_info=None):
        """Process received response from supplier"""
        self.ensure_one()
        
        if self.state != 'sent':
            _logger.warning("Received response for inquiry %s in state %s", self.inquiry_id, self.state)
            return
        
        # Parse response for pricing information
        parsed_info = self._parse_supplier_response(response_text)
        
        # Update inquiry record
        update_vals = {
            'state': 'responded',
            'response_received_date': fields.Datetime.now(),
            'supplier_response': response_text,
            'communication_log': (self.communication_log or '') + f"\n\nReceived at {fields.Datetime.now()}: {response_text}"
        }
        
        # Add parsed information
        update_vals.update(parsed_info)
        
        self.write(update_vals)
        
        # Notify the sales request
        self.sales_request_id._handle_supplier_response(self)
        
        _logger.info("Response received for inquiry %s from supplier %s", self.inquiry_id, self.supplier_id.name)
    
    def _parse_supplier_response(self, response_text):
        """Parse supplier response to extract pricing and delivery information"""
        parsed_info = {}
        
        # Simple parsing logic - can be enhanced with AI
        response_lower = response_text.lower()
        
        # Try to extract price
        import re
        
        # Look for price patterns (Vietnamese format)
        price_patterns = [
            r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:đ|vnd|vnđ)',
            r'giá[:\s]*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)',
            r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:nghìn|triệu|k|m)',
        ]
        
        for pattern in price_patterns:
            match = re.search(pattern, response_lower)
            if match:
                price_str = match.group(1).replace(',', '').replace('.', '')
                try:
                    parsed_info['quoted_price'] = float(price_str)
                    parsed_info['quoted_currency'] = 'VND'
                    break
                except ValueError:
                    continue
        
        # Look for delivery time
        delivery_patterns = [
            r'giao\s*(?:hàng)?\s*(?:trong)?\s*(\d+)\s*(?:ngày|tuần|tháng)',
            r'thời\s*gian\s*giao\s*(?:hàng)?\s*[:\s]*(\d+)\s*(?:ngày|tuần|tháng)',
            r'(\d+)\s*(?:ngày|tuần|tháng)\s*(?:giao|có\s*hàng)',
        ]
        
        for pattern in delivery_patterns:
            match = re.search(pattern, response_lower)
            if match:
                parsed_info['delivery_time'] = match.group(0)
                break
        
        # Look for minimum order quantity
        moq_patterns = [
            r'tối\s*thiểu\s*(\d+)',
            r'đặt\s*ít\s*nhất\s*(\d+)',
            r'moq[:\s]*(\d+)',
        ]
        
        for pattern in moq_patterns:
            match = re.search(pattern, response_lower)
            if match:
                try:
                    parsed_info['minimum_order_qty'] = float(match.group(1))
                    break
                except ValueError:
                    continue
        
        return parsed_info
    
    def _schedule_timeout_check(self):
        """Schedule a timeout check for this inquiry"""
        # This would typically be handled by a cron job
        # For now, we'll just set the expected response date
        pass
    
    def action_mark_timeout(self):
        """Mark inquiry as timeout"""
        self.ensure_one()
        if self.state == 'sent':
            self.write({
                'state': 'timeout',
                'communication_log': (self.communication_log or '') + f"\n\nTimeout at {fields.Datetime.now()}: No response received within expected time"
            })
            _logger.info("Inquiry %s marked as timeout", self.inquiry_id)
    
    def action_retry_inquiry(self):
        """Retry sending the inquiry"""
        self.ensure_one()
        if self.retry_count >= 3:
            raise UserError(_("Maximum retry attempts reached for this inquiry"))
        
        self.write({
            'state': 'draft',
            'retry_count': self.retry_count + 1,
            'last_retry_date': fields.Datetime.now()
        })
        self.action_send_inquiry()
    
    @api.model
    def check_timeouts(self):
        """Cron job method to check for timed out inquiries"""
        timeout_inquiries = self.search([
            ('state', '=', 'sent'),
            ('expected_response_date', '<', fields.Datetime.now())
        ])
        
        for inquiry in timeout_inquiries:
            inquiry.action_mark_timeout()
        
        _logger.info("Checked %d inquiries for timeout", len(timeout_inquiries))
        return True