# -*- coding: utf-8 -*-

import json
import hmac
import hashlib
import logging
from odoo import http, fields, _
from odoo.http import request
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class ZaloChatWebhook(http.Controller):
    """Controller to handle Zalo OA chat webhooks"""

    @http.route('/zalo/chat/webhook', type='json', auth='public', csrf=False, methods=['POST'])
    def zalo_chat_webhook(self, **kwargs):
        """
        Webhook endpoint to receive chat messages from Zalo OA
        
        Expected webhook events:
        - user_send_text
        - user_send_image
        - user_send_sticker
        - user_send_file
        - user_send_audio
        - user_send_video
        - user_send_location
        """
        try:
            # Get request data
            data = request.jsonrequest
            _logger.info(f'Received Zalo webhook: {json.dumps(data)}')
            
            # Verify webhook signature (optional but recommended)
            # TODO: Implement signature verification with OA Secret Key
            
            # Extract event information
            event_name = data.get('event_name')
            app_id = data.get('app_id')
            timestamp = data.get('timestamp')
            
            sender = data.get('sender', {})
            recipient = data.get('recipient', {})
            message_data = data.get('message', {})
            
            zalo_user_id = sender.get('id')
            
            if not zalo_user_id:
                _logger.warning('No sender ID in webhook data')
                return {'error': 0, 'message': 'No sender ID'}
            
            # Find or create conversation
            Conversation = request.env['zalo.chat.conversation'].sudo()
            
            # Try to get user info from Zalo if needed
            user_info = {
                'name': sender.get('name', 'Zalo User'),
                'avatar': sender.get('avatar', ''),
            }
            
            conversation = Conversation._find_or_create_conversation(
                zalo_user_id,
                user_info
            )
            
            # Process message based on event type
            message_vals = {
                'conversation_id': conversation.id,
                'message_id': message_data.get('msg_id'),
                'direction': 'inbound',
                'sent_date': fields.Datetime.now(),
                'state': 'delivered',
                'is_read': False,
            }
            
            # Parse message content based on type
            if event_name == 'user_send_text':
                message_vals.update({
                    'message_type': 'text',
                    'content': message_data.get('text', ''),
                })
            
            elif event_name == 'user_send_image':
                message_vals.update({
                    'message_type': 'image',
                    'content': _('(Image)'),
                    'attachment_url': message_data.get('url', ''),
                })
            
            elif event_name == 'user_send_sticker':
                message_vals.update({
                    'message_type': 'sticker',
                    'content': _('(Sticker)'),
                    'attachment_url': message_data.get('url', ''),
                })
            
            elif event_name == 'user_send_file':
                attachments = message_data.get('attachments', [])
                file_url = attachments[0].get('payload', {}).get('url', '') if attachments else ''
                message_vals.update({
                    'message_type': 'file',
                    'content': _('(File)'),
                    'attachment_url': file_url,
                })
            
            elif event_name == 'user_send_audio':
                message_vals.update({
                    'message_type': 'audio',
                    'content': _('(Audio)'),
                    'attachment_url': message_data.get('url', ''),
                })
            
            elif event_name == 'user_send_video':
                message_vals.update({
                    'message_type': 'video',
                    'content': _('(Video)'),
                    'attachment_url': message_data.get('url', ''),
                })
            
            elif event_name == 'user_send_location':
                location = message_data.get('location', {})
                message_vals.update({
                    'message_type': 'location',
                    'content': f"Location: {location.get('latitude', '')}, {location.get('longitude', '')}",
                })
            
            else:
                _logger.warning(f'Unknown event type: {event_name}')
                return {'error': 0, 'message': 'Event type not supported'}
            
            # Create message record
            Message = request.env['zalo.chat.message'].sudo()
            message = Message.create(message_vals)
            
            # Post notification to conversation chatter
            notification_body = Markup(
                _('<b>New message from %s:</b><br/>%s')
            ) % (
                conversation.zalo_user_name or 'Zalo User',
                message.content or _('(attachment)')
            )
            conversation.message_post(body=notification_body)
            
            # Reopen conversation if it was closed
            if conversation.state == 'closed':
                conversation.write({'state': 'open'})
            
            _logger.info(f'Processed Zalo webhook message: {message.id}')
            
            # Return success response
            return {'error': 0, 'message': 'success'}
        
        except Exception as e:
            _logger.error(f'Error processing Zalo webhook: {str(e)}', exc_info=True)
            # Still return success to Zalo to avoid retry storms
            return {'error': 0, 'message': 'processed with errors'}
