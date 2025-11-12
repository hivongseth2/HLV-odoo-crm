import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

class SupplierContact(models.Model):
    _name = 'hlv.ai.supplier.contact'
    _description = 'AI Sales Supplier Contact'
    _rec_name = 'name'
    _order = 'priority desc, name'

    name = fields.Char('Supplier Name', required=True)
    active = fields.Boolean('Active', default=True)
    priority = fields.Integer('Priority', default=10, help='Higher priority suppliers will be contacted first')
    
    # Contact Information
    zalo_user_id = fields.Char('Zalo User ID', required=True, 
        help='Zalo User ID for sending messages via Zalo OA')
    phone = fields.Char('Phone Number')
    email = fields.Char('Email')
    contact_person = fields.Char('Contact Person')
    
    # Business Information
    partner_id = fields.Many2one('res.partner', string='Related Partner', 
        help='Link to existing partner/vendor record')
    company = fields.Char('Company Name')
    address = fields.Text('Address')
    
    # Product Categories
    product_category_ids = fields.Many2many('product.category', 
        string='Product Categories',
        help='Product categories this supplier can provide')
    product_tags = fields.Text('Product Tags', 
        help='Comma-separated tags for products this supplier provides')
    
    # Communication Settings
    preferred_language = fields.Selection([
        ('vi_VN', 'Vietnamese'),
        ('en_US', 'English'),
    ], string='Preferred Language', default='vi_VN')
    
    response_time_hours = fields.Integer('Expected Response Time (Hours)', default=24,
        help='Expected response time for inquiries')
    
    # Statistics
    total_inquiries = fields.Integer('Total Inquiries', compute='_compute_inquiry_stats', store=True)
    successful_responses = fields.Integer('Successful Responses', compute='_compute_inquiry_stats', store=True)
    response_rate = fields.Float('Response Rate (%)', compute='_compute_inquiry_stats', store=True)
    last_inquiry_date = fields.Datetime('Last Inquiry Date', compute='_compute_inquiry_stats', store=True)
    
    # Related Records
    inquiry_ids = fields.One2many('hlv.ai.product.inquiry', 'supplier_id', string='Product Inquiries')
    
    @api.depends('inquiry_ids', 'inquiry_ids.state')
    def _compute_inquiry_stats(self):
        for record in self:
            inquiries = record.inquiry_ids
            record.total_inquiries = len(inquiries)
            record.successful_responses = len(inquiries.filtered(lambda x: x.state == 'responded'))
            record.response_rate = (record.successful_responses / record.total_inquiries * 100) if record.total_inquiries > 0 else 0
            record.last_inquiry_date = max(inquiries.mapped('create_date')) if inquiries else False
    
    @api.constrains('zalo_user_id')
    def _check_zalo_user_id(self):
        for record in self:
            if record.zalo_user_id:
                existing = self.search([
                    ('zalo_user_id', '=', record.zalo_user_id),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(_('Zalo User ID must be unique. Another supplier already uses this ID.'))
    
    @api.constrains('priority')
    def _check_priority(self):
        for record in self:
            if record.priority < 0:
                raise ValidationError(_('Priority cannot be negative'))
    
    def send_inquiry_message(self, product_name, description, quantity, unit):
        """Send inquiry message to supplier via Zalo"""
        self.ensure_one()
        
        # Get AI config for message template
        ai_config = self.env['hlv.ai.sales.config'].get_default_config()
        
        # Format message using template
        message = ai_config.supplier_inquiry_prompt.format(
            product_name=product_name,
            description=description,
            quantity=quantity,
            unit=unit
        )
        
        try:
            # Get Zalo ZNS config
            zalo_config = self.env['hlv.zalo.zns'].search([('active', '=', True)], limit=1)
            if not zalo_config:
                raise Exception(_("No active Zalo ZNS configuration found"))
            
            # Send message via Zalo
            # Note: This assumes the Zalo module supports direct messaging
            # You might need to adapt this based on the actual Zalo module capabilities
            response = zalo_config.send_zns(
                msisdn=self.zalo_user_id,
                params={'message': message}
            )
            
            _logger.info("Sent inquiry to supplier %s via Zalo: %s", self.name, response)
            return response
            
        except Exception as e:
            _logger.error("Failed to send inquiry to supplier %s: %s", self.name, str(e))
            raise
    
    def action_test_zalo_connection(self):
        """Test Zalo connection by sending a test message"""
        self.ensure_one()
        try:
            test_message = f"Xin chào {self.contact_person or 'anh/chị'}, đây là tin nhắn test từ hệ thống AI Sales Support của HLV. Vui lòng phản hồi để xác nhận kết nối."
            
            zalo_config = self.env['hlv.zalo.zns'].search([('active', '=', True)], limit=1)
            if not zalo_config:
                raise Exception(_("No active Zalo ZNS configuration found"))
            
            response = zalo_config.send_zns(
                msisdn=self.zalo_user_id,
                params={'message': test_message}
            )
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Test message sent successfully to %s') % self.name,
                    'type': 'success',
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Failed to send test message: %s') % str(e),
                    'type': 'danger',
                }
            }
    
    @api.model
    def get_suppliers_for_product(self, product_categories=None, product_tags=None):
        """Get suitable suppliers for a product based on categories and tags"""
        domain = [('active', '=', True)]
        
        if product_categories:
            domain.append(('product_category_ids', 'in', product_categories.ids))
        
        suppliers = self.search(domain, order='priority desc, response_rate desc')
        
        # If product_tags provided, filter by tags
        if product_tags and suppliers:
            filtered_suppliers = self.env['hlv.ai.supplier.contact']
            for supplier in suppliers:
                if supplier.product_tags:
                    supplier_tags = [tag.strip().lower() for tag in supplier.product_tags.split(',')]
                    if any(tag.lower() in supplier_tags for tag in product_tags):
                        filtered_suppliers |= supplier
            return filtered_suppliers if filtered_suppliers else suppliers
        
        return suppliers