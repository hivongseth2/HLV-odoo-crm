import json
import logging
from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)

class ZaloWebhook(http.Controller):
    
    @http.route('/webhook/zalo/ai_sales', type='json', auth='public', methods=['POST'], csrf=False)
    def handle_zalo_webhook(self, **kwargs):
        """
        Handle incoming Zalo webhook for AI Sales Support
        
        This endpoint receives messages from suppliers responding to product inquiries
        """
        try:
            _logger.info("Received Zalo webhook: %s", kwargs)
            
            # Extract message data from webhook
            event_name = kwargs.get('event_name')
            
            if event_name == 'user_send_text':
                return self._handle_text_message(kwargs)
            elif event_name == 'user_send_image':
                return self._handle_image_message(kwargs)
            else:
                _logger.info("Unhandled Zalo event: %s", event_name)
                return {'status': 'ignored', 'message': 'Event type not handled'}
            
        except Exception as e:
            _logger.exception("Error handling Zalo webhook: %s", str(e))
            return {'status': 'error', 'message': str(e)}
    
    def _handle_text_message(self, webhook_data):
        """Handle text message from Zalo"""
        try:
            # Extract message details
            sender = webhook_data.get('sender', {})
            message = webhook_data.get('message', {})
            
            sender_id = sender.get('id')
            message_text = message.get('text', '')
            timestamp = webhook_data.get('timestamp')
            
            if not sender_id or not message_text:
                return {'status': 'error', 'message': 'Missing sender ID or message text'}
            
            _logger.info("Processing text message from %s: %s", sender_id, message_text)
            
            # Find supplier by Zalo user ID
            supplier = request.env['hlv.ai.supplier.contact'].sudo().search([
                ('zalo_user_id', '=', sender_id),
                ('active', '=', True)
            ], limit=1)
            
            if not supplier:
                _logger.warning("No supplier found for Zalo user ID: %s", sender_id)
                return {'status': 'ignored', 'message': 'Supplier not found'}
            
            # Find pending inquiries for this supplier
            pending_inquiries = request.env['hlv.ai.product.inquiry'].sudo().search([
                ('supplier_id', '=', supplier.id),
                ('state', '=', 'sent')
            ], order='sent_date desc')
            
            if not pending_inquiries:
                _logger.info("No pending inquiries found for supplier %s", supplier.name)
                # This might be a general message, log it but don't process as inquiry response
                return {'status': 'ignored', 'message': 'No pending inquiries'}
            
            # Process the response for the most recent inquiry
            # In a more sophisticated system, you might use AI to match the response to the correct inquiry
            latest_inquiry = pending_inquiries[0]
            
            # Process the supplier response
            latest_inquiry.action_receive_response(
                response_text=message_text,
                sender_info={
                    'sender_id': sender_id,
                    'timestamp': timestamp,
                    'webhook_data': webhook_data
                }
            )
            
            return {
                'status': 'success',
                'message': f'Response processed for inquiry {latest_inquiry.inquiry_id}'
            }
            
        except Exception as e:
            _logger.exception("Error processing text message: %s", str(e))
            return {'status': 'error', 'message': str(e)}
    
    def _handle_image_message(self, webhook_data):
        """Handle image message from Zalo (e.g., price list, product catalog)"""
        try:
            sender = webhook_data.get('sender', {})
            message = webhook_data.get('message', {})
            
            sender_id = sender.get('id')
            attachments = message.get('attachments', [])
            
            if not sender_id or not attachments:
                return {'status': 'error', 'message': 'Missing sender ID or attachments'}
            
            _logger.info("Processing image message from %s with %d attachments", sender_id, len(attachments))
            
            # Find supplier
            supplier = request.env['hlv.ai.supplier.contact'].sudo().search([
                ('zalo_user_id', '=', sender_id),
                ('active', '=', True)
            ], limit=1)
            
            if not supplier:
                return {'status': 'ignored', 'message': 'Supplier not found'}
            
            # Find pending inquiries
            pending_inquiries = request.env['hlv.ai.product.inquiry'].sudo().search([
                ('supplier_id', '=', supplier.id),
                ('state', '=', 'sent')
            ], order='sent_date desc')
            
            if not pending_inquiries:
                return {'status': 'ignored', 'message': 'No pending inquiries'}
            
            # Process image attachments
            attachment_info = []
            for attachment in attachments:
                attachment_info.append({
                    'type': attachment.get('type'),
                    'payload': attachment.get('payload', {})
                })
            
            # For now, just log the image and add a note to the inquiry
            latest_inquiry = pending_inquiries[0]
            
            response_text = f"[Nhà cung cấp đã gửi {len(attachments)} hình ảnh/tài liệu]"
            if message.get('text'):
                response_text += f"\n{message['text']}"
            
            latest_inquiry.action_receive_response(
                response_text=response_text,
                sender_info={
                    'sender_id': sender_id,
                    'attachments': attachment_info,
                    'webhook_data': webhook_data
                }
            )
            
            return {
                'status': 'success',
                'message': f'Image response processed for inquiry {latest_inquiry.inquiry_id}'
            }
            
        except Exception as e:
            _logger.exception("Error processing image message: %s", str(e))
            return {'status': 'error', 'message': str(e)}
    
    @http.route('/webhook/zalo/ai_sales/verify', type='http', auth='public', methods=['GET'], csrf=False)
    def verify_webhook(self, **kwargs):
        """
        Verify Zalo webhook endpoint
        
        Zalo sends a verification request when setting up the webhook
        """
        try:
            # Zalo webhook verification typically involves echoing back a challenge
            challenge = kwargs.get('hub.challenge')
            verify_token = kwargs.get('hub.verify_token')
            
            # You should configure the expected verify token in your Zalo app settings
            expected_token = request.env['ir.config_parameter'].sudo().get_param(
                'hlv_ai_sales.zalo_verify_token', 'default_verify_token'
            )
            
            if verify_token == expected_token:
                _logger.info("Zalo webhook verification successful")
                return challenge or 'OK'
            else:
                _logger.warning("Zalo webhook verification failed: invalid token")
                return 'Verification failed', 403
                
        except Exception as e:
            _logger.exception("Error verifying Zalo webhook: %s", str(e))
            return 'Error', 500
    
    @http.route('/api/ai_sales/webhook/test', type='json', auth='public', methods=['POST'])
    def test_webhook(self, **kwargs):
        """
        Test endpoint for webhook functionality
        """
        try:
            _logger.info("Test webhook called with data: %s", kwargs)
            
            # Simulate a supplier response
            test_data = {
                'event_name': 'user_send_text',
                'sender': {'id': kwargs.get('sender_id', 'test_supplier')},
                'message': {'text': kwargs.get('message', 'Test response: Giá 50,000 VND/cái, giao hàng trong 3 ngày')},
                'timestamp': kwargs.get('timestamp', '1234567890')
            }
            
            result = self.handle_zalo_webhook(**test_data)
            
            return {
                'success': True,
                'test_data': test_data,
                'result': result
            }
            
        except Exception as e:
            _logger.exception("Error in test webhook: %s", str(e))
            return {
                'success': False,
                'error': str(e)
            }