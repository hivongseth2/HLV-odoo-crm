# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SupplierContact(models.Model):
    _name = 'ai.sales.supplier.contact'
    _description = 'Supplier Contact Information for AI Sales'
    _rec_name = 'supplier_name'

    supplier_id = fields.Many2one(
        'res.partner',
        string='Supplier',
        domain=[('is_company', '=', True), ('supplier_rank', '>', 0)],
        required=True,
        help='Supplier partner record'
    )
    
    supplier_name = fields.Char(
        related='supplier_id.name',
        string='Supplier Name',
        store=True,
        readonly=True
    )
    
    zalo_user_id = fields.Char(
        string='Zalo User ID',
        required=True,
        help='Zalo user ID for this supplier contact'
    )
    
    zalo_phone = fields.Char(
        string='Zalo Phone Number',
        help='Phone number associated with Zalo account'
    )
    
    contact_person = fields.Char(
        string='Contact Person',
        help='Name of the contact person at supplier'
    )
    
    contact_position = fields.Char(
        string='Position',
        help='Position/title of the contact person'
    )
    
    is_active = fields.Boolean(
        string='Active',
        default=True,
        help='Whether this contact is active for AI sales communication'
    )
    
    priority = fields.Selection([
        ('1', 'Low'),
        ('2', 'Normal'),
        ('3', 'High'),
        ('4', 'Very High'),
    ], string='Priority', default='2',
       help='Priority level for contacting this supplier')
    
    response_time_avg = fields.Float(
        string='Average Response Time (hours)',
        help='Average time this supplier takes to respond'
    )
    
    last_contact_date = fields.Datetime(
        string='Last Contact Date',
        help='Last time this supplier was contacted via AI system'
    )
    
    success_rate = fields.Float(
        string='Success Rate (%)',
        help='Percentage of successful communications with this supplier'
    )
    
    notes = fields.Text(
        string='Notes',
        help='Additional notes about this supplier contact'
    )
    
    # Product categories this supplier handles
    product_category_ids = fields.Many2many(
        'product.category',
        string='Product Categories',
        help='Product categories this supplier can provide'
    )
    
    # Communication log
    communication_log_ids = fields.One2many(
        'ai.sales.communication.log',
        'supplier_contact_id',
        string='Communication Log'
    )

    @api.model
    def get_suppliers_for_product(self, product_id):
        """Get suppliers that can provide a specific product"""
        product = self.env['product.product'].browse(product_id)
        if not product.exists():
            return self.browse([])
        
        # Get suppliers based on product category
        suppliers = self.search([
            ('is_active', '=', True),
            ('product_category_ids', 'in', product.categ_id.ids)
        ])
        
        # If no category match, get all active suppliers
        if not suppliers:
            suppliers = self.search([('is_active', '=', True)])
        
        # Sort by priority and success rate
        return suppliers.sorted(key=lambda s: (s.priority, -s.success_rate), reverse=True)

    def update_communication_stats(self, success=True, response_time=None):
        """Update communication statistics"""
        self.last_contact_date = fields.Datetime.now()
        
        if response_time:
            if self.response_time_avg:
                # Calculate moving average
                self.response_time_avg = (self.response_time_avg + response_time) / 2
            else:
                self.response_time_avg = response_time
        
        # Update success rate (simple moving average)
        if self.success_rate:
            if success:
                self.success_rate = min(100, self.success_rate + 1)
            else:
                self.success_rate = max(0, self.success_rate - 2)
        else:
            self.success_rate = 100 if success else 0


class CommunicationLog(models.Model):
    _name = 'ai.sales.communication.log'
    _description = 'AI Sales Communication Log'
    _order = 'create_date desc'

    supplier_contact_id = fields.Many2one(
        'ai.sales.supplier.contact',
        string='Supplier Contact',
        required=True,
        ondelete='cascade'
    )
    
    inquiry_id = fields.Many2one(
        'ai.sales.inquiry',
        string='Sales Inquiry',
        ondelete='cascade'
    )
    
    message_type = fields.Selection([
        ('outgoing', 'Outgoing'),
        ('incoming', 'Incoming'),
    ], string='Message Type', required=True)
    
    message_content = fields.Text(
        string='Message Content',
        required=True
    )
    
    zalo_message_id = fields.Char(
        string='Zalo Message ID',
        help='Zalo message ID for tracking'
    )
    
    status = fields.Selection([
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('replied', 'Replied'),
        ('failed', 'Failed'),
    ], string='Status', default='sent')
    
    response_time = fields.Float(
        string='Response Time (hours)',
        help='Time taken to receive response'
    )
    
    is_successful = fields.Boolean(
        string='Successful',
        default=True,
        help='Whether the communication was successful'
    )