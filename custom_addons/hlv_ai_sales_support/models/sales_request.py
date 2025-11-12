import logging
import json
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class SalesRequest(models.Model):
    _name = 'hlv.ai.sales.request'
    _description = 'AI Sales Request'
    _rec_name = 'request_id'
    _order = 'create_date desc'

    # Basic Information
    request_id = fields.Char('Request ID', required=True, copy=False, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('hlv.ai.sales.request') or 'New')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('analyzing', 'AI Analyzing'),
        ('checking_stock', 'Checking Stock'),
        ('contacting_suppliers', 'Contacting Suppliers'),
        ('waiting_response', 'Waiting Supplier Response'),
        ('preparing_quote', 'Preparing Quotation'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('error', 'Error'),
    ], string='Status', default='draft', tracking=True)
    
    # Request Details
    sales_person = fields.Char('Sales Person', required=True, help='Name of the sales person making the request')
    sales_email = fields.Char('Sales Email', help='Email of the sales person')
    customer_name = fields.Char('Customer Name', help='Name of the customer')
    
    # Product Information (Original Request)
    original_request = fields.Text('Original Request', required=True,
        help='Original product information and quantity request from sales')
    
    # AI Analysis Results
    ai_analysis = fields.Text('AI Analysis', readonly=True,
        help='AI analysis results in JSON format')
    analyzed_product_name = fields.Char('Analyzed Product Name', readonly=True)
    analyzed_description = fields.Text('Analyzed Description', readonly=True)
    analyzed_category = fields.Char('Analyzed Category', readonly=True)
    analyzed_keywords = fields.Text('Analyzed Keywords', readonly=True)
    requested_quantity = fields.Float('Requested Quantity', readonly=True)
    requested_unit = fields.Char('Requested Unit', readonly=True)
    
    # Product Matching
    matched_product_ids = fields.Many2many('product.product', string='Matched Products',
        help='Products found in inventory that match the request')
    selected_product_id = fields.Many2one('product.product', string='Selected Product',
        help='Final selected product for the quotation')
    
    # Stock Information
    stock_available = fields.Float('Available Stock', readonly=True)
    stock_sufficient = fields.Boolean('Stock Sufficient', readonly=True)
    stock_check_details = fields.Text('Stock Check Details', readonly=True)
    
    # Supplier Communication
    inquiry_ids = fields.One2many('hlv.ai.product.inquiry', 'sales_request_id', string='Supplier Inquiries')
    suppliers_contacted = fields.Integer('Suppliers Contacted', compute='_compute_supplier_stats')
    suppliers_responded = fields.Integer('Suppliers Responded', compute='_compute_supplier_stats')
    
    # Quotation Information
    unit_price = fields.Float('Unit Price')
    total_price = fields.Float('Total Price', compute='_compute_total_price', store=True)
    currency_id = fields.Many2one('res.currency', string='Currency', 
        default=lambda self: self.env.company.currency_id)
    quotation_valid_until = fields.Date('Quotation Valid Until')
    
    # Response
    response_ids = fields.One2many('hlv.ai.sales.response', 'sales_request_id', string='Responses')
    final_response = fields.Text('Final Response', readonly=True)
    response_sent = fields.Boolean('Response Sent', readonly=True)
    response_sent_date = fields.Datetime('Response Sent Date', readonly=True)
    
    # Timestamps
    processing_started = fields.Datetime('Processing Started')
    processing_completed = fields.Datetime('Processing Completed')
    processing_duration = fields.Float('Processing Duration (minutes)', compute='_compute_processing_duration')
    
    # Error Handling
    error_message = fields.Text('Error Message', readonly=True)
    retry_count = fields.Integer('Retry Count', default=0)
    
    @api.depends('inquiry_ids', 'inquiry_ids.state')
    def _compute_supplier_stats(self):
        for record in self:
            record.suppliers_contacted = len(record.inquiry_ids)
            record.suppliers_responded = len(record.inquiry_ids.filtered(lambda x: x.state == 'responded'))
    
    @api.depends('requested_quantity', 'unit_price')
    def _compute_total_price(self):
        for record in self:
            record.total_price = record.requested_quantity * record.unit_price
    
    @api.depends('processing_started', 'processing_completed')
    def _compute_processing_duration(self):
        for record in self:
            if record.processing_started and record.processing_completed:
                delta = record.processing_completed - record.processing_started
                record.processing_duration = delta.total_seconds() / 60
            else:
                record.processing_duration = 0
    
    @api.model
    def create(self, vals):
        if vals.get('request_id', 'New') == 'New':
            vals['request_id'] = self.env['ir.sequence'].next_by_code('hlv.ai.sales.request') or 'New'
        return super().create(vals)
    
    def action_start_processing(self):
        """Start processing the sales request"""
        self.ensure_one()
        self.write({
            'state': 'analyzing',
            'processing_started': fields.Datetime.now()
        })
        self._process_request()
    
    def _process_request(self):
        """Main processing logic"""
        try:
            # Step 1: AI Analysis
            self._analyze_with_ai()
            
            # Step 2: Product Matching
            self._match_products()
            
            # Step 3: Stock Check
            self._check_stock()
            
            # Step 4: Handle based on stock availability
            if self.stock_sufficient:
                self._prepare_quotation_from_stock()
            else:
                self._contact_suppliers()
                
        except Exception as e:
            _logger.exception("Error processing sales request %s: %s", self.request_id, str(e))
            self.write({
                'state': 'error',
                'error_message': str(e),
                'processing_completed': fields.Datetime.now()
            })
    
    def _analyze_with_ai(self):
        """Analyze the request using AI"""
        self.write({'state': 'analyzing'})
        
        ai_config = self.env['hlv.ai.sales.config'].get_default_config()
        analysis_result = ai_config.analyze_product_with_ai(self.original_request)
        
        # Store analysis results
        update_vals = {
            'ai_analysis': json.dumps(analysis_result, ensure_ascii=False, indent=2),
            'analyzed_product_name': analysis_result.get('product_name', ''),
            'analyzed_description': analysis_result.get('description', ''),
            'analyzed_category': analysis_result.get('category', ''),
            'analyzed_keywords': ', '.join(analysis_result.get('keywords', [])),
            'requested_quantity': analysis_result.get('quantity', 0),
            'requested_unit': analysis_result.get('unit', ''),
        }
        self.write(update_vals)
        
        _logger.info("AI analysis completed for request %s", self.request_id)
    
    def _match_products(self):
        """Match products in inventory based on AI analysis"""
        if not self.analyzed_product_name and not self.analyzed_keywords:
            return
        
        # Search products by name and keywords
        domain = []
        if self.analyzed_product_name:
            domain.append(('name', 'ilike', self.analyzed_product_name))
        
        if self.analyzed_keywords:
            keywords = [kw.strip() for kw in self.analyzed_keywords.split(',')]
            for keyword in keywords:
                domain.append('|')
                domain.append(('name', 'ilike', keyword))
                domain.append(('description', 'ilike', keyword))
        
        if domain:
            products = self.env['product.product'].search(domain)
            self.matched_product_ids = [(6, 0, products.ids)]
            
            # Auto-select the first product if only one match
            if len(products) == 1:
                self.selected_product_id = products[0]
        
        _logger.info("Found %d matching products for request %s", len(self.matched_product_ids), self.request_id)
    
    def _check_stock(self):
        """Check stock availability"""
        self.write({'state': 'checking_stock'})
        
        if not self.selected_product_id:
            # If no specific product selected, check the first matched product
            if self.matched_product_ids:
                self.selected_product_id = self.matched_product_ids[0]
            else:
                self.write({
                    'stock_sufficient': False,
                    'stock_check_details': 'No matching products found in inventory'
                })
                return
        
        product = self.selected_product_id
        ai_config = self.env['hlv.ai.sales.config'].get_default_config()
        
        # Get stock quantity
        if ai_config.check_all_warehouses:
            stock_qty = product.qty_available
        else:
            # Check main warehouse only
            main_warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
            if main_warehouse:
                stock_qty = product.with_context(warehouse=main_warehouse.id).qty_available
            else:
                stock_qty = product.qty_available
        
        # Apply buffer
        required_qty = self.requested_quantity
        buffer_qty = required_qty * (ai_config.stock_buffer_percentage / 100)
        total_required = required_qty + buffer_qty
        
        sufficient = stock_qty >= total_required
        
        self.write({
            'stock_available': stock_qty,
            'stock_sufficient': sufficient,
            'stock_check_details': f'Available: {stock_qty}, Required: {required_qty}, Buffer: {buffer_qty}, Sufficient: {sufficient}',
            'unit_price': product.list_price,
        })
        
        _logger.info("Stock check completed for request %s: %s", self.request_id, sufficient)
    
    def _prepare_quotation_from_stock(self):
        """Prepare quotation when stock is sufficient"""
        self.write({'state': 'preparing_quote'})
        
        ai_config = self.env['hlv.ai.sales.config'].get_default_config()
        
        # Set quotation validity
        self.quotation_valid_until = fields.Date.today() + timedelta(days=ai_config.quotation_validity_days)
        
        # Prepare response
        response_text = f"""Báo giá sản phẩm:

Sản phẩm: {self.selected_product_id.name}
Mô tả: {self.selected_product_id.description or 'N/A'}
Số lượng: {self.requested_quantity} {self.requested_unit}
Đơn giá: {self.unit_price:,.0f} {self.currency_id.name}
Thành tiền: {self.total_price:,.0f} {self.currency_id.name}

Tình trạng: Có sẵn trong kho
Thời gian giao hàng: Ngay khi có đơn hàng
Báo giá có hiệu lực đến: {self.quotation_valid_until}

Vui lòng liên hệ để xác nhận đơn hàng."""
        
        self._create_response(response_text)
        self._complete_processing()
    
    def _contact_suppliers(self):
        """Contact suppliers when stock is insufficient"""
        self.write({'state': 'contacting_suppliers'})
        
        # Find suitable suppliers
        suppliers = self.env['hlv.ai.supplier.contact'].get_suppliers_for_product(
            product_categories=self.selected_product_id.categ_id if self.selected_product_id else None,
            product_tags=self.analyzed_keywords.split(',') if self.analyzed_keywords else None
        )
        
        if not suppliers:
            self.write({
                'state': 'error',
                'error_message': 'No suitable suppliers found for this product',
                'processing_completed': fields.Datetime.now()
            })
            return
        
        # Create inquiries for suppliers
        for supplier in suppliers[:3]:  # Contact top 3 suppliers
            inquiry = self.env['hlv.ai.product.inquiry'].create({
                'sales_request_id': self.id,
                'supplier_id': supplier.id,
                'product_name': self.analyzed_product_name,
                'description': self.analyzed_description,
                'quantity': self.requested_quantity,
                'unit': self.requested_unit,
            })
            inquiry.action_send_inquiry()
        
        self.write({'state': 'waiting_response'})
        _logger.info("Contacted %d suppliers for request %s", len(suppliers[:3]), self.request_id)
    
    def _create_response(self, response_text):
        """Create response record"""
        self.env['hlv.ai.sales.response'].create({
            'sales_request_id': self.id,
            'response_text': response_text,
            'response_type': 'quotation',
        })
        
        self.write({
            'final_response': response_text,
            'response_sent': True,
            'response_sent_date': fields.Datetime.now()
        })
    
    def _complete_processing(self):
        """Complete the processing"""
        self.write({
            'state': 'completed',
            'processing_completed': fields.Datetime.now()
        })
        _logger.info("Sales request %s completed successfully", self.request_id)
    
    def action_retry_processing(self):
        """Retry processing after error"""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'error_message': False,
            'retry_count': self.retry_count + 1,
            'processing_started': False,
            'processing_completed': False
        })
        self.action_start_processing()
    
    def action_cancel(self):
        """Cancel the request"""
        self.ensure_one()
        self.write({
            'state': 'cancelled',
            'processing_completed': fields.Datetime.now()
        })
    
    def _handle_supplier_response(self, inquiry):
        """Handle response from supplier"""
        self.ensure_one()
        
        # Check if we have enough responses to proceed
        responded_inquiries = self.inquiry_ids.filtered(lambda x: x.state == 'responded')
        
        if not responded_inquiries:
            return
        
        # Find the best quote
        best_inquiry = min(responded_inquiries, key=lambda x: x.quoted_price or float('inf'))
        
        if best_inquiry.quoted_price:
            # Update pricing information
            self.write({
                'unit_price': best_inquiry.quoted_price,
                'state': 'preparing_quote'
            })
            
            # Set quotation validity
            ai_config = self.env['hlv.ai.sales.config'].get_default_config()
            self.quotation_valid_until = fields.Date.today() + timedelta(days=ai_config.quotation_validity_days)
            
            # Prepare response with supplier quote
            response_text = f"""Báo giá sản phẩm từ nhà cung cấp:

Sản phẩm: {self.analyzed_product_name}
Mô tả: {self.analyzed_description}
Số lượng: {self.requested_quantity} {self.requested_unit}
Đơn giá: {self.unit_price:,.0f} {best_inquiry.quoted_currency or 'VND'}
Thành tiền: {self.total_price:,.0f} {best_inquiry.quoted_currency or 'VND'}

Nhà cung cấp: {best_inquiry.supplier_id.name}
Thời gian giao hàng: {best_inquiry.delivery_time or 'Liên hệ để xác nhận'}
Số lượng tối thiểu: {best_inquiry.minimum_order_qty or 'Không yêu cầu'}

Báo giá có hiệu lực đến: {self.quotation_valid_until}

Vui lòng liên hệ để xác nhận đơn hàng."""
            
            self._create_response(response_text)
            self._complete_processing()
        
        _logger.info("Processed supplier response for request %s", self.request_id)