# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from unittest.mock import patch, MagicMock
import json


class TestAISalesSupport(TransactionCase):
    
    def setUp(self):
        super().setUp()
        
        # Create test data
        self.partner = self.env['res.partner'].create({
            'name': 'Test Customer',
            'email': 'test@example.com',
        })
        
        self.supplier = self.env['res.partner'].create({
            'name': 'Test Supplier',
            'is_company': True,
            'supplier_rank': 1,
        })
        
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'default_code': 'TEST001',
            'list_price': 100.0,
            'type': 'product',
        })
        
        # Create supplier contact
        self.supplier_contact = self.env['ai.sales.supplier.contact'].create({
            'supplier_id': self.supplier.id,
            'contact_person': 'John Doe',
            'zalo_user_id': '123456789',
            'zalo_phone': '0123456789',
        })
        
        # Configure AI settings
        self.env['ir.config_parameter'].sudo().set_param('ai_sales_support.ai_sales_enabled', True)
        self.env['ir.config_parameter'].sudo().set_param('ai_sales_support.chatgpt_api_key', 'test-key')
        
    def test_create_inquiry(self):
        """Test creating an AI sales inquiry"""
        inquiry = self.env['ai.sales.inquiry'].create({
            'sales_person_id': self.env.user.id,
            'customer_id': self.partner.id,
            'inquiry_text': 'I need 5 units of TEST001',
        })
        
        self.assertTrue(inquiry.inquiry_reference)
        self.assertEqual(inquiry.state, 'draft')
        self.assertEqual(inquiry.sales_person_id, self.env.user)
        
    def test_inquiry_sequence(self):
        """Test inquiry reference sequence generation"""
        inquiry1 = self.env['ai.sales.inquiry'].create({
            'sales_person_id': self.env.user.id,
            'inquiry_text': 'Test inquiry 1',
        })
        
        inquiry2 = self.env['ai.sales.inquiry'].create({
            'sales_person_id': self.env.user.id,
            'inquiry_text': 'Test inquiry 2',
        })
        
        self.assertTrue(inquiry1.inquiry_reference.startswith('ASI'))
        self.assertTrue(inquiry2.inquiry_reference.startswith('ASI'))
        self.assertNotEqual(inquiry1.inquiry_reference, inquiry2.inquiry_reference)
        
    def test_supplier_contact_creation(self):
        """Test supplier contact creation and validation"""
        contact = self.env['ai.sales.supplier.contact'].create({
            'supplier_id': self.supplier.id,
            'contact_person': 'Jane Smith',
            'zalo_user_id': '987654321',
            'zalo_phone': '0987654321',
            'priority': '3',
        })
        
        self.assertEqual(contact.supplier_name, self.supplier.name)
        self.assertEqual(contact.priority, '3')
        self.assertTrue(contact.is_active)
        
    @patch('requests.post')
    def test_ai_service_chatgpt_integration(self, mock_post):
        """Test ChatGPT API integration"""
        # Mock ChatGPT response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': json.dumps({
                        'products': [
                            {
                                'name': 'Test Product',
                                'code': 'TEST001',
                                'quantity': 5,
                                'description': 'Test product description'
                            }
                        ],
                        'analysis': 'Customer needs 5 units of TEST001'
                    })
                }
            }]
        }
        mock_post.return_value = mock_response
        
        # Create inquiry
        inquiry = self.env['ai.sales.inquiry'].create({
            'sales_person_id': self.env.user.id,
            'inquiry_text': 'I need 5 units of TEST001',
        })
        
        # Process with AI service
        ai_service = self.env['ai.sales.service']
        result = ai_service.process_inquiry(inquiry.id)
        
        self.assertTrue(result.get('success'))
        self.assertTrue(mock_post.called)
        
    def test_inventory_check(self):
        """Test inventory checking functionality"""
        # Create stock for product
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.env.ref('stock.stock_location_stock').id,
            'quantity': 10.0,
        })
        
        inquiry = self.env['ai.sales.inquiry'].create({
            'sales_person_id': self.env.user.id,
            'inquiry_text': 'I need 5 units of TEST001',
        })
        
        # Create inquiry line
        line = self.env['ai.sales.inquiry.line'].create({
            'inquiry_id': inquiry.id,
            'product_id': self.product.id,
            'product_code': 'TEST001',
            'product_name': 'Test Product',
            'quantity': 5.0,
        })
        
        # Check inventory
        ai_service = self.env['ai.sales.service']
        ai_service._check_inventory_availability(inquiry)
        
        line.refresh()
        self.assertTrue(line.is_sufficient)
        self.assertEqual(line.available_qty, 10.0)
        
    def test_quotation_creation(self):
        """Test quotation creation from inquiry"""
        inquiry = self.env['ai.sales.inquiry'].create({
            'sales_person_id': self.env.user.id,
            'customer_id': self.partner.id,
            'inquiry_text': 'I need 5 units of TEST001',
            'state': 'quotation_ready',
        })
        
        # Create inquiry line
        self.env['ai.sales.inquiry.line'].create({
            'inquiry_id': inquiry.id,
            'product_id': self.product.id,
            'product_code': 'TEST001',
            'product_name': 'Test Product',
            'quantity': 5.0,
            'unit_price': 100.0,
            'is_sufficient': True,
        })
        
        # Create quotation
        ai_service = self.env['ai.sales.service']
        quotation = ai_service.create_quotation(inquiry.id)
        
        self.assertTrue(quotation)
        self.assertEqual(quotation.partner_id, self.partner)
        self.assertEqual(len(quotation.order_line), 1)
        self.assertEqual(quotation.order_line[0].product_id, self.product)
        self.assertEqual(quotation.order_line[0].product_uom_qty, 5.0)
        
    def test_communication_log(self):
        """Test communication log creation"""
        log = self.env['ai.sales.communication.log'].create({
            'supplier_contact_id': self.supplier_contact.id,
            'message_type': 'outgoing',
            'message_content': 'Test message to supplier',
            'status': 'sent',
        })
        
        self.assertEqual(log.supplier_contact_id, self.supplier_contact)
        self.assertEqual(log.message_type, 'outgoing')
        self.assertEqual(log.status, 'sent')
        
    def test_config_settings(self):
        """Test configuration settings"""
        config = self.env['res.config.settings'].create({
            'ai_sales_enabled': True,
            'chatgpt_api_key': 'test-api-key',
            'chatgpt_model': 'gpt-3.5-turbo',
            'zalo_oa_access_token': 'test-zalo-token',
        })
        
        config.execute()
        
        # Check if settings are saved
        self.assertTrue(self.env['ir.config_parameter'].sudo().get_param('ai_sales_support.ai_sales_enabled'))
        self.assertEqual(
            self.env['ir.config_parameter'].sudo().get_param('ai_sales_support.chatgpt_api_key'),
            'test-api-key'
        )
        
    def test_inquiry_state_transitions(self):
        """Test inquiry state transitions"""
        inquiry = self.env['ai.sales.inquiry'].create({
            'sales_person_id': self.env.user.id,
            'inquiry_text': 'Test inquiry',
        })
        
        # Test state transitions
        self.assertEqual(inquiry.state, 'draft')
        
        inquiry.start_processing()
        self.assertEqual(inquiry.state, 'processing')
        
        inquiry.state = 'quotation_ready'
        inquiry.complete_processing()
        self.assertEqual(inquiry.state, 'completed')
        
    def test_supplier_performance_tracking(self):
        """Test supplier performance tracking"""
        # Create successful communication
        self.env['ai.sales.communication.log'].create({
            'supplier_contact_id': self.supplier_contact.id,
            'message_type': 'outgoing',
            'message_content': 'Test message',
            'status': 'replied',
            'is_successful': True,
            'response_time': 2.5,
        })
        
        # Create failed communication
        self.env['ai.sales.communication.log'].create({
            'supplier_contact_id': self.supplier_contact.id,
            'message_type': 'outgoing',
            'message_content': 'Test message 2',
            'status': 'failed',
            'is_successful': False,
            'response_time': 0.0,
        })
        
        # Update performance metrics
        self.supplier_contact._compute_performance_metrics()
        
        # Check calculated metrics
        self.assertEqual(self.supplier_contact.success_rate, 50.0)  # 1 success out of 2
        self.assertEqual(self.supplier_contact.response_time_avg, 2.5)  # Only successful responses counted