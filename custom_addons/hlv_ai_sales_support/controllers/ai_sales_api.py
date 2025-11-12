import json
import logging
from odoo import http, _
from odoo.http import request
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

class AISalesAPI(http.Controller):
    
    @http.route('/api/ai_sales/request', type='json', auth='public', methods=['POST'], csrf=False)
    def create_sales_request(self, **kwargs):
        """
        API endpoint to create a new sales request
        
        Expected JSON payload:
        {
            "sales_person": "Anh Quang",
            "sales_email": "quang@hlv.com",
            "customer_name": "Khách hàng ABC",
            "product_request": "Tôi cần 100 cái ốc vít M6x20mm inox 304"
        }
        """
        try:
            # Validate required fields
            required_fields = ['sales_person', 'product_request']
            for field in required_fields:
                if not kwargs.get(field):
                    return {
                        'success': False,
                        'error': f'Missing required field: {field}',
                        'error_code': 'MISSING_FIELD'
                    }
            
            # Create sales request
            sales_request = request.env['hlv.ai.sales.request'].sudo().create({
                'sales_person': kwargs['sales_person'],
                'sales_email': kwargs.get('sales_email'),
                'customer_name': kwargs.get('customer_name'),
                'original_request': kwargs['product_request'],
            })
            
            # Start processing asynchronously
            sales_request.action_start_processing()
            
            return {
                'success': True,
                'request_id': sales_request.request_id,
                'status': sales_request.state,
                'message': 'Sales request created and processing started'
            }
            
        except Exception as e:
            _logger.exception("Error creating sales request: %s", str(e))
            return {
                'success': False,
                'error': str(e),
                'error_code': 'INTERNAL_ERROR'
            }
    
    @http.route('/api/ai_sales/status/<string:request_id>', type='json', auth='public', methods=['GET'])
    def get_request_status(self, request_id, **kwargs):
        """
        Get the status of a sales request
        """
        try:
            sales_request = request.env['hlv.ai.sales.request'].sudo().search([
                ('request_id', '=', request_id)
            ], limit=1)
            
            if not sales_request:
                return {
                    'success': False,
                    'error': 'Request not found',
                    'error_code': 'NOT_FOUND'
                }
            
            response_data = {
                'success': True,
                'request_id': sales_request.request_id,
                'status': sales_request.state,
                'sales_person': sales_request.sales_person,
                'customer_name': sales_request.customer_name,
                'processing_started': sales_request.processing_started.isoformat() if sales_request.processing_started else None,
                'processing_completed': sales_request.processing_completed.isoformat() if sales_request.processing_completed else None,
            }
            
            # Add analysis results if available
            if sales_request.ai_analysis:
                try:
                    response_data['ai_analysis'] = json.loads(sales_request.ai_analysis)
                except:
                    response_data['ai_analysis'] = sales_request.ai_analysis
            
            # Add stock information if available
            if sales_request.selected_product_id:
                response_data['product'] = {
                    'id': sales_request.selected_product_id.id,
                    'name': sales_request.selected_product_id.name,
                    'stock_available': sales_request.stock_available,
                    'stock_sufficient': sales_request.stock_sufficient,
                    'unit_price': sales_request.unit_price,
                    'total_price': sales_request.total_price,
                }
            
            # Add supplier information if contacted
            if sales_request.inquiry_ids:
                response_data['supplier_inquiries'] = [{
                    'supplier_name': inquiry.supplier_id.name,
                    'status': inquiry.state,
                    'sent_date': inquiry.sent_date.isoformat() if inquiry.sent_date else None,
                    'quoted_price': inquiry.quoted_price,
                    'delivery_time': inquiry.delivery_time,
                } for inquiry in sales_request.inquiry_ids]
            
            # Add final response if available
            if sales_request.final_response:
                response_data['final_response'] = sales_request.final_response
                response_data['response_sent'] = sales_request.response_sent
                response_data['response_sent_date'] = sales_request.response_sent_date.isoformat() if sales_request.response_sent_date else None
            
            # Add error information if any
            if sales_request.error_message:
                response_data['error_message'] = sales_request.error_message
            
            return response_data
            
        except Exception as e:
            _logger.exception("Error getting request status: %s", str(e))
            return {
                'success': False,
                'error': str(e),
                'error_code': 'INTERNAL_ERROR'
            }
    
    @http.route('/api/ai_sales/requests', type='json', auth='public', methods=['GET'])
    def list_requests(self, **kwargs):
        """
        List sales requests with optional filtering
        
        Query parameters:
        - sales_person: Filter by sales person
        - status: Filter by status
        - limit: Limit number of results (default 50)
        - offset: Offset for pagination (default 0)
        """
        try:
            domain = []
            
            # Apply filters
            if kwargs.get('sales_person'):
                domain.append(('sales_person', 'ilike', kwargs['sales_person']))
            
            if kwargs.get('status'):
                domain.append(('state', '=', kwargs['status']))
            
            # Pagination
            limit = min(int(kwargs.get('limit', 50)), 100)  # Max 100 records
            offset = int(kwargs.get('offset', 0))
            
            # Search requests
            sales_requests = request.env['hlv.ai.sales.request'].sudo().search(
                domain, limit=limit, offset=offset, order='create_date desc'
            )
            
            # Format response
            requests_data = []
            for req in sales_requests:
                req_data = {
                    'request_id': req.request_id,
                    'status': req.state,
                    'sales_person': req.sales_person,
                    'customer_name': req.customer_name,
                    'create_date': req.create_date.isoformat(),
                    'processing_duration': req.processing_duration,
                }
                
                if req.selected_product_id:
                    req_data['product_name'] = req.selected_product_id.name
                    req_data['total_price'] = req.total_price
                
                requests_data.append(req_data)
            
            return {
                'success': True,
                'requests': requests_data,
                'total_count': len(requests_data),
                'has_more': len(requests_data) == limit
            }
            
        except Exception as e:
            _logger.exception("Error listing requests: %s", str(e))
            return {
                'success': False,
                'error': str(e),
                'error_code': 'INTERNAL_ERROR'
            }
    
    @http.route('/api/ai_sales/retry/<string:request_id>', type='json', auth='public', methods=['POST'])
    def retry_request(self, request_id, **kwargs):
        """
        Retry processing a failed request
        """
        try:
            sales_request = request.env['hlv.ai.sales.request'].sudo().search([
                ('request_id', '=', request_id)
            ], limit=1)
            
            if not sales_request:
                return {
                    'success': False,
                    'error': 'Request not found',
                    'error_code': 'NOT_FOUND'
                }
            
            if sales_request.state not in ['error', 'cancelled']:
                return {
                    'success': False,
                    'error': 'Request cannot be retried in current state',
                    'error_code': 'INVALID_STATE'
                }
            
            sales_request.action_retry_processing()
            
            return {
                'success': True,
                'request_id': sales_request.request_id,
                'status': sales_request.state,
                'message': 'Request retry initiated'
            }
            
        except Exception as e:
            _logger.exception("Error retrying request: %s", str(e))
            return {
                'success': False,
                'error': str(e),
                'error_code': 'INTERNAL_ERROR'
            }
    
    @http.route('/api/ai_sales/cancel/<string:request_id>', type='json', auth='public', methods=['POST'])
    def cancel_request(self, request_id, **kwargs):
        """
        Cancel a pending request
        """
        try:
            sales_request = request.env['hlv.ai.sales.request'].sudo().search([
                ('request_id', '=', request_id)
            ], limit=1)
            
            if not sales_request:
                return {
                    'success': False,
                    'error': 'Request not found',
                    'error_code': 'NOT_FOUND'
                }
            
            if sales_request.state in ['completed', 'cancelled']:
                return {
                    'success': False,
                    'error': 'Request cannot be cancelled in current state',
                    'error_code': 'INVALID_STATE'
                }
            
            sales_request.action_cancel()
            
            return {
                'success': True,
                'request_id': sales_request.request_id,
                'status': sales_request.state,
                'message': 'Request cancelled successfully'
            }
            
        except Exception as e:
            _logger.exception("Error cancelling request: %s", str(e))
            return {
                'success': False,
                'error': str(e),
                'error_code': 'INTERNAL_ERROR'
            }
    
    @http.route('/api/ai_sales/health', type='json', auth='public', methods=['GET'])
    def health_check(self, **kwargs):
        """
        Health check endpoint
        """
        try:
            # Check if AI config is available
            ai_config = request.env['hlv.ai.sales.config'].sudo().search([('active', '=', True)], limit=1)
            ai_config_status = bool(ai_config and ai_config.openai_api_key)
            
            # Check if Zalo config is available
            zalo_config = request.env['hlv.zalo.zns'].sudo().search([('active', '=', True)], limit=1)
            zalo_config_status = bool(zalo_config)
            
            return {
                'success': True,
                'status': 'healthy',
                'services': {
                    'ai_config': ai_config_status,
                    'zalo_config': zalo_config_status,
                },
                'timestamp': request.env.cr.now().isoformat()
            }
            
        except Exception as e:
            _logger.exception("Health check failed: %s", str(e))
            return {
                'success': False,
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': request.env.cr.now().isoformat()
            }