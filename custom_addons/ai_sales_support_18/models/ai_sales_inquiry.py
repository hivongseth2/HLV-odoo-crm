# -*- coding: utf-8 -*-

from odoo import models, fields, api
import json
from datetime import datetime, timedelta


class AISalesInquiry(models.Model):
    _name = 'ai.sales.inquiry'
    _description = 'AI Sales Inquiry'
    _order = 'create_date desc'
    _rec_name = 'inquiry_reference'

    inquiry_reference = fields.Char(
        string='Inquiry Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('ai.sales.inquiry') or 'New'
    )
    
    sales_person_id = fields.Many2one(
        'res.users',
        string='Sales Person',
        required=True,
        default=lambda self: self.env.user,
        help='Sales person who made the inquiry'
    )
    
    customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        help='Customer for this inquiry'
    )
    
    inquiry_text = fields.Text(
        string='Original Inquiry',
        required=True,
        help='Original text from sales person'
    )
    
    processed_inquiry = fields.Text(
        string='Processed Inquiry',
        help='AI processed and structured inquiry'
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processing', 'Processing'),
        ('inventory_check', 'Checking Inventory'),
        ('supplier_contact', 'Contacting Suppliers'),
        ('quotation_ready', 'Quotation Ready'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ], string='Status', default='draft', tracking=True)
    
    # Product Information
    product_lines = fields.One2many(
        'ai.sales.inquiry.line',
        'inquiry_id',
        string='Product Lines'
    )
    
    # AI Response
    ai_response = fields.Text(
        string='AI Response',
        help='Final response from AI system'
    )
    
    ai_analysis = fields.Text(
        string='AI Analysis',
        help='AI analysis of the inquiry'
    )
    
    # Inventory Check Results
    inventory_sufficient = fields.Boolean(
        string='Inventory Sufficient',
        help='Whether inventory is sufficient for all requested products'
    )
    
    inventory_check_details = fields.Text(
        string='Inventory Check Details',
        help='Detailed inventory check results'
    )
    
    # Supplier Communication
    suppliers_contacted = fields.Many2many(
        'ai.sales.supplier.contact',
        string='Suppliers Contacted',
        help='Suppliers that were contacted for this inquiry'
    )
    
    supplier_responses = fields.Text(
        string='Supplier Responses',
        help='Responses received from suppliers'
    )
    
    # Quotation
    quotation_id = fields.Many2one(
        'sale.order',
        string='Generated Quotation',
        help='Quotation generated from this inquiry'
    )
    
    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        help='Total amount of the quotation'
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )
    
    # Timing
    processing_start_time = fields.Datetime(
        string='Processing Start Time'
    )
    
    processing_end_time = fields.Datetime(
        string='Processing End Time'
    )
    
    processing_duration = fields.Float(
        string='Processing Duration (minutes)',
        compute='_compute_processing_duration',
        store=True
    )
    
    # Communication Log
    communication_log_ids = fields.One2many(
        'ai.sales.communication.log',
        'inquiry_id',
        string='Communication Log'
    )
    
    notes = fields.Text(
        string='Notes',
        help='Additional notes about this inquiry'
    )

    @api.depends('processing_start_time', 'processing_end_time')
    def _compute_processing_duration(self):
        for record in self:
            if record.processing_start_time and record.processing_end_time:
                delta = record.processing_end_time - record.processing_start_time
                record.processing_duration = delta.total_seconds() / 60
            else:
                record.processing_duration = 0

    @api.model
    def create(self, vals):
        if vals.get('inquiry_reference', 'New') == 'New':
            vals['inquiry_reference'] = self.env['ir.sequence'].next_by_code('ai.sales.inquiry') or 'New'
        return super(AISalesInquiry, self).create(vals)

    def start_processing(self):
        """Start processing the inquiry"""
        self.write({
            'state': 'processing',
            'processing_start_time': fields.Datetime.now()
        })

    def complete_processing(self):
        """Complete processing the inquiry"""
        self.write({
            'state': 'completed',
            'processing_end_time': fields.Datetime.now()
        })

    def fail_processing(self, error_message=None):
        """Mark processing as failed"""
        self.write({
            'state': 'failed',
            'processing_end_time': fields.Datetime.now(),
            'notes': error_message or 'Processing failed'
        })

    def create_quotation(self):
        """Create a sale order from this inquiry"""
        if not self.customer_id:
            raise ValueError("Customer is required to create quotation")
        
        sale_order = self.env['sale.order'].create({
            'partner_id': self.customer_id.id,
            'user_id': self.sales_person_id.id,
            'origin': self.inquiry_reference,
            'note': f"Generated from AI Sales Inquiry: {self.inquiry_reference}\n\nOriginal Inquiry: {self.inquiry_text}"
        })
        
        # Add product lines
        for line in self.product_lines:
            if line.product_id:
                self.env['sale.order.line'].create({
                    'order_id': sale_order.id,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'price_unit': line.unit_price,
                    'name': line.description or line.product_id.name,
                })
        
        self.quotation_id = sale_order.id
        return sale_order


class AISalesInquiryLine(models.Model):
    _name = 'ai.sales.inquiry.line'
    _description = 'AI Sales Inquiry Line'

    inquiry_id = fields.Many2one(
        'ai.sales.inquiry',
        string='Inquiry',
        required=True,
        ondelete='cascade'
    )
    
    sequence = fields.Integer(
        string='Sequence',
        default=10
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product'
    )
    
    product_code = fields.Char(
        string='Product Code',
        help='Product code from inquiry'
    )
    
    product_name = fields.Char(
        string='Product Name',
        help='Product name from inquiry'
    )
    
    description = fields.Text(
        string='Description',
        help='Product description from inquiry'
    )
    
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        help='Requested quantity'
    )
    
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        help='Unit of measure'
    )
    
    # Inventory Information
    available_qty = fields.Float(
        string='Available Quantity',
        help='Available quantity in stock'
    )
    
    is_sufficient = fields.Boolean(
        string='Sufficient Stock',
        help='Whether available stock is sufficient'
    )
    
    # Pricing Information
    unit_price = fields.Monetary(
        string='Unit Price',
        currency_field='currency_id'
    )
    
    supplier_price = fields.Monetary(
        string='Supplier Price',
        currency_field='currency_id',
        help='Price from supplier if contacted'
    )
    
    markup_percentage = fields.Float(
        string='Markup %',
        help='Markup percentage applied'
    )
    
    subtotal = fields.Monetary(
        string='Subtotal',
        currency_field='currency_id',
        compute='_compute_subtotal',
        store=True
    )
    
    currency_id = fields.Many2one(
        related='inquiry_id.currency_id',
        string='Currency'
    )
    
    # Supplier Information
    supplier_id = fields.Many2one(
        'res.partner',
        string='Supplier',
        help='Supplier for this product'
    )
    
    supplier_response_time = fields.Float(
        string='Supplier Response Time (hours)',
        help='Time taken by supplier to respond'
    )
    
    notes = fields.Text(
        string='Notes',
        help='Additional notes for this line'
    )

    @api.depends('quantity', 'unit_price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.unit_price

    def check_inventory(self):
        """Check inventory for this product line"""
        if not self.product_id:
            return False
        
        # Get available quantity
        available_qty = self.product_id.qty_available
        self.available_qty = available_qty
        self.is_sufficient = available_qty >= self.quantity
        
        return self.is_sufficient

    def get_product_price(self):
        """Get product price"""
        if not self.product_id:
            return 0.0
        
        # Get list price
        price = self.product_id.list_price
        
        # Apply markup if supplier price is available
        if self.supplier_price and self.markup_percentage:
            price = self.supplier_price * (1 + self.markup_percentage / 100)
        
        self.unit_price = price
        return price