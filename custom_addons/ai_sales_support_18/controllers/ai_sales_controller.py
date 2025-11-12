# -*- coding: utf-8 -*-

import json
import logging
from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class AISalesController(http.Controller):

    @http.route('/ai_sales/inquiry', type='json', auth='user', methods=['POST'], csrf=False)
    def process_inquiry(self, **kwargs):
        """
        Process sales inquiry from authenticated user
        """
        try:
            inquiry_text = kwargs.get('inquiry_text', '').strip()
            customer_id = kwargs.get('customer_id')
            
            if not inquiry_text:
                return {
                    'success': False,
                    'error': 'Inquiry text is required',
                    'message': 'Vui lòng nhập nội dung yêu cầu'
                }
            
            # Check if AI Sales Support is enabled
            config = request.env['ir.config_parameter'].sudo()
            if not config.get_param('ai_sales_support.enabled', False):
                return {
                    'success': False,
                    'error': 'AI Sales Support is disabled',
                    'message': 'Tính năng AI Sales Support chưa được kích hoạt'
                }
            
            # Process the inquiry
            ai_service = request.env['ai.sales.service']
            result = ai_service.process_sales_inquiry(
                inquiry_text=inquiry_text,
                sales_person_id=request.env.user.id,
                customer_id=customer_id
            )
            
            return result
            
        except Exception as e:
            _logger.error(f"Error in AI sales inquiry: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'message': 'Đã có lỗi xảy ra khi xử lý yêu cầu'
            }

    @http.route('/ai_sales/status', type='json', auth='user', methods=['GET'])
    def get_status(self):
        """
        Get AI Sales Support status
        """
        try:
            config = request.env['ir.config_parameter'].sudo()
            enabled = config.get_param('ai_sales_support.enabled', False)
            
            if enabled:
                # Check if API keys are configured
                chatgpt_key = config.get_param('ai_sales_support.chatgpt_api_key')
                zalo_token = config.get_param('ai_sales_support.zalo_oa_access_token')
                
                return {
                    'enabled': True,
                    'chatgpt_configured': bool(chatgpt_key),
                    'zalo_configured': bool(zalo_token),
                    'user': request.env.user.name
                }
            else:
                return {
                    'enabled': False,
                    'message': 'AI Sales Support is not enabled'
                }
                
        except Exception as e:
            _logger.error(f"Error getting AI sales status: {str(e)}")
            return {
                'enabled': False,
                'error': str(e)
            }

    @http.route('/ai_sales/inquiries', type='json', auth='user', methods=['GET'])
    def get_inquiries(self, **kwargs):
        """
        Get user's inquiries
        """
        try:
            limit = kwargs.get('limit', 20)
            offset = kwargs.get('offset', 0)
            
            domain = [('sales_person_id', '=', request.env.user.id)]
            
            inquiries = request.env['ai.sales.inquiry'].search(
                domain, 
                limit=limit, 
                offset=offset, 
                order='create_date desc'
            )
            
            result = []
            for inquiry in inquiries:
                result.append({
                    'id': inquiry.id,
                    'reference': inquiry.inquiry_reference,
                    'inquiry_text': inquiry.inquiry_text,
                    'state': inquiry.state,
                    'ai_response': inquiry.ai_response,
                    'total_amount': inquiry.total_amount,
                    'create_date': inquiry.create_date.isoformat() if inquiry.create_date else None,
                    'customer': inquiry.customer_id.name if inquiry.customer_id else None,
                    'processing_duration': inquiry.processing_duration
                })
            
            return {
                'success': True,
                'inquiries': result,
                'total': request.env['ai.sales.inquiry'].search_count(domain)
            }
            
        except Exception as e:
            _logger.error(f"Error getting inquiries: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    @http.route('/ai_sales/inquiry/<int:inquiry_id>', type='json', auth='user', methods=['GET'])
    def get_inquiry_detail(self, inquiry_id):
        """
        Get detailed inquiry information
        """
        try:
            inquiry = request.env['ai.sales.inquiry'].browse(inquiry_id)
            
            if not inquiry.exists():
                return {
                    'success': False,
                    'error': 'Inquiry not found'
                }
            
            # Check access rights
            if inquiry.sales_person_id.id != request.env.user.id:
                return {
                    'success': False,
                    'error': 'Access denied'
                }
            
            # Get product lines
            lines = []
            for line in inquiry.product_lines:
                lines.append({
                    'id': line.id,
                    'product_name': line.product_name,
                    'product_code': line.product_code,
                    'description': line.description,
                    'quantity': line.quantity,
                    'unit_price': line.unit_price,
                    'subtotal': line.subtotal,
                    'available_qty': line.available_qty,
                    'is_sufficient': line.is_sufficient,
                    'supplier': line.supplier_id.name if line.supplier_id else None
                })
            
            # Get communication log
            communications = []
            for comm in inquiry.communication_log_ids:
                communications.append({
                    'id': comm.id,
                    'message_type': comm.message_type,
                    'message_content': comm.message_content,
                    'status': comm.status,
                    'create_date': comm.create_date.isoformat() if comm.create_date else None,
                    'supplier': comm.supplier_contact_id.supplier_name if comm.supplier_contact_id else None
                })
            
            return {
                'success': True,
                'inquiry': {
                    'id': inquiry.id,
                    'reference': inquiry.inquiry_reference,
                    'inquiry_text': inquiry.inquiry_text,
                    'processed_inquiry': inquiry.processed_inquiry,
                    'state': inquiry.state,
                    'ai_response': inquiry.ai_response,
                    'ai_analysis': inquiry.ai_analysis,
                    'total_amount': inquiry.total_amount,
                    'inventory_sufficient': inquiry.inventory_sufficient,
                    'inventory_check_details': inquiry.inventory_check_details,
                    'supplier_responses': inquiry.supplier_responses,
                    'create_date': inquiry.create_date.isoformat() if inquiry.create_date else None,
                    'processing_duration': inquiry.processing_duration,
                    'customer': inquiry.customer_id.name if inquiry.customer_id else None,
                    'quotation_id': inquiry.quotation_id.id if inquiry.quotation_id else None,
                    'lines': lines,
                    'communications': communications
                }
            }
            
        except Exception as e:
            _logger.error(f"Error getting inquiry detail: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    @http.route('/ai_sales/create_quotation', type='json', auth='user', methods=['POST'])
    def create_quotation(self, **kwargs):
        """
        Create quotation from inquiry
        """
        try:
            inquiry_id = kwargs.get('inquiry_id')
            customer_id = kwargs.get('customer_id')
            
            if not inquiry_id:
                return {
                    'success': False,
                    'error': 'Inquiry ID is required'
                }
            
            inquiry = request.env['ai.sales.inquiry'].browse(inquiry_id)
            
            if not inquiry.exists():
                return {
                    'success': False,
                    'error': 'Inquiry not found'
                }
            
            # Check access rights
            if inquiry.sales_person_id.id != request.env.user.id:
                return {
                    'success': False,
                    'error': 'Access denied'
                }
            
            # Set customer if provided
            if customer_id and not inquiry.customer_id:
                inquiry.customer_id = customer_id
            
            if not inquiry.customer_id:
                return {
                    'success': False,
                    'error': 'Customer is required to create quotation'
                }
            
            # Create quotation
            quotation = inquiry.create_quotation()
            
            return {
                'success': True,
                'quotation_id': quotation.id,
                'quotation_name': quotation.name,
                'message': 'Quotation created successfully'
            }
            
        except Exception as e:
            _logger.error(f"Error creating quotation: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    @http.route('/ai_sales/webhook/zalo', type='json', auth='none', methods=['POST'], csrf=False)
    def zalo_webhook(self, **kwargs):
        """
        Handle Zalo webhook for supplier responses
        """
        try:
            # Verify webhook (you should implement proper verification)
            data = request.jsonrequest
            
            if data.get('event_name') == 'user_send_text':
                user_id = data.get('sender', {}).get('id')
                message = data.get('message', {}).get('text', '')
                
                if user_id and message:
                    # Process supplier response
                    ai_service = request.env['ai.sales.service'].sudo()
                    ai_service.handle_supplier_response(user_id, message)
            
            return {'status': 'ok'}
            
        except Exception as e:
            _logger.error(f"Error in Zalo webhook: {str(e)}")
            return {'status': 'error', 'message': str(e)}

    @http.route('/ai_sales/suppliers', type='json', auth='user', methods=['GET'])
    def get_suppliers(self):
        """
        Get list of configured suppliers
        """
        try:
            suppliers = request.env['ai.sales.supplier.contact'].search([
                ('is_active', '=', True)
            ])
            
            result = []
            for supplier in suppliers:
                result.append({
                    'id': supplier.id,
                    'name': supplier.supplier_name,
                    'contact_person': supplier.contact_person,
                    'zalo_user_id': supplier.zalo_user_id,
                    'priority': supplier.priority,
                    'success_rate': supplier.success_rate,
                    'response_time_avg': supplier.response_time_avg,
                    'last_contact_date': supplier.last_contact_date.isoformat() if supplier.last_contact_date else None
                })
            
            return {
                'success': True,
                'suppliers': result
            }
            
        except Exception as e:
            _logger.error(f"Error getting suppliers: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    @http.route('/ai_sales/test', type='http', auth='user', methods=['GET'])
    def test_page(self):
        """
        Test page for AI Sales Support
        """
        return request.render('ai_sales_support_18.test_page', {
            'user': request.env.user,
            'company': request.env.company
        })