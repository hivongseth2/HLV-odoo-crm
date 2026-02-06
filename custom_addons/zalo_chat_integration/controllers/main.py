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

    @http.route('/zalo/chat/webhook', type='http', auth='public', csrf=False, methods=['POST', 'GET'])
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
        - oa_send_text
        """
        try:
            # Handle GET request for webhook verification
            if request.httprequest.method == 'GET':
                _logger.info('Received Zalo webhook verification (GET)')
                return request.make_response('OK', headers=[('Content-Type', 'text/plain')])
            
            # Get request data
            try:
                data = json.loads(request.httprequest.data.decode('utf-8'))
            except:
                data = request.params
            
            _logger.info(f'Received Zalo webhook event: {data.get("event_name")}')
            
            # Return success immediately to avoid timeout
            # Process message in separate transaction
            request.env.cr.commit()
            
            try:
                self._process_webhook_data(data)
            except Exception as e:
                _logger.error(f'Error processing webhook data: {str(e)}', exc_info=True)
            
            # Return success response
            return request.make_response(
                json.dumps({'error': 0, 'message': 'success'}),
                headers=[('Content-Type', 'application/json')]
            )
        
        except Exception as e:
            _logger.error(f'Error in webhook endpoint: {str(e)}', exc_info=True)
            return request.make_response(
                json.dumps({'error': 0, 'message': 'processed'}),
                headers=[('Content-Type', 'application/json')]
            )
    
    def _process_webhook_data(self, data):
        """Process webhook data in separate method"""
        # Verify webhook signature (optional but recommended)
        # TODO: Implement signature verification with OA Secret Key
        
        # Extract event information
        event_name = data.get('event_name')
        app_id = data.get('app_id')
        timestamp = data.get('timestamp')
        
        _logger.info(f'[ZALO WEBHOOK] ========== NEW EVENT ==========')
        _logger.info(f'[ZALO WEBHOOK] event_name={event_name}, app_id={app_id}, timestamp={timestamp}')
        _logger.info(f'[ZALO WEBHOOK] Full data: {json.dumps(data, ensure_ascii=False)[:500]}')
        
        sender = data.get('sender', {})
        recipient = data.get('recipient', {})
        message_data = data.get('message', {})
        
        _logger.info(f'[ZALO WEBHOOK] sender={sender}, recipient={recipient}')
        _logger.info(f'[ZALO WEBHOOK] message_data={message_data}')
        
        # IMPORTANT: For oa_send_text, sender is OA and recipient is user
        # For user_send_*, sender is user
        if event_name == 'oa_send_text':
            # OA sent message to user - user is in recipient
            zalo_user_id = recipient.get('id')
            _logger.info(f'[ZALO WEBHOOK] oa_send_text - extracting recipient as zalo_user_id={zalo_user_id}')
        else:
            # User sent message to OA - user is in sender  
            zalo_user_id = sender.get('id')
            _logger.info(f'[ZALO WEBHOOK] {event_name} - extracting sender as zalo_user_id={zalo_user_id}')
        
        if not zalo_user_id:
            _logger.warning(f'[ZALO WEBHOOK] No user ID in webhook data for event {event_name}')
            return
        
        # Find or create conversation
        Conversation = request.env['zalo.chat.conversation'].sudo()
        
        _logger.info(f'[ZALO WEBHOOK] Finding/creating conversation for zalo_user_id={zalo_user_id}')
        
        # CRITICAL: Pass None for user_info to force fetching from Zalo API
        # Webhook data only has minimal info (id), we need full profile
        # This fixes "Public user" issue by getting real display_name, avatar, etc.
        conversation = Conversation._find_or_create_conversation(
            zalo_user_id,
            user_info=None  # Force API fetch
        )
        
        _logger.info(f'[ZALO WEBHOOK] Got conversation id={conversation.id}, name={conversation.zalo_user_name}, partner={conversation.partner_id.id if conversation.partner_id else None}')
        
        # Process message based on event type
        # Initialize skip flag - only skip for outbound OA messages
        skip_discuss_sync = False
        
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
            # Image from Zalo
            attachments = message_data.get('attachments', [])
            image_url = attachments[0].get('payload', {}).get('url', '') if attachments else message_data.get('url', '')
            message_vals.update({
                'message_type': 'image',
                'content': _('📷 Image'),
                'attachment_url': image_url,
            })
        
        elif event_name == 'user_send_gif':
            # GIF animation
            attachments = message_data.get('attachments', [])
            gif_url = attachments[0].get('payload', {}).get('url', '') if attachments else message_data.get('url', '')
            message_vals.update({
                'message_type': 'gif',
                'content': _('🎬 GIF'),
                'attachment_url': gif_url,
            })
        
        elif event_name == 'user_send_sticker':
            # Sticker
            attachments = message_data.get('attachments', [])
            sticker_url = attachments[0].get('payload', {}).get('url', '') if attachments else message_data.get('url', '')
            message_vals.update({
                'message_type': 'sticker',
                'content': _('😊 Sticker'),
                'attachment_url': sticker_url,
            })
        
        elif event_name == 'user_send_link':
            # Link/URL
            links = message_data.get('attachments', [{}])[0].get('payload', {}).get('elements', [])
            link_url = links[0].get('url', '') if links else message_data.get('text', '')
            link_title = links[0].get('title', '') if links else ''
            message_vals.update({
                'message_type': 'link',
                'content': f"🔗 {link_title or 'Link'}: {link_url}",
            })
        
        elif event_name == 'user_send_file':
            # File attachment
            attachments = message_data.get('attachments', [])
            file_url = attachments[0].get('payload', {}).get('url', '') if attachments else message_data.get('url', '')
            # Extract filename from attachment data or URL
            file_name = 'file'
            if attachments:
                file_name = attachments[0].get('payload', {}).get('name', '')
            if not file_name and file_url:
                # Try to extract from URL
                file_name = file_url.split('/')[-1].split('?')[0] or 'file'
            message_vals.update({
                'message_type': 'file',
                'content': f"📎 File: {file_name}",
                'attachment_url': file_url,
            })
        
        elif event_name == 'user_send_audio':
            # Audio/voice message
            attachments = message_data.get('attachments', [])
            audio_url = attachments[0].get('payload', {}).get('url', '') if attachments else message_data.get('url', '')
            message_vals.update({
                'message_type': 'audio',
                'content': _('🎤 Voice message'),
                'attachment_url': audio_url,
            })
        
        elif event_name == 'user_send_video':
            # Video message
            attachments = message_data.get('attachments', [])
            video_url = attachments[0].get('payload', {}).get('url', '') if attachments else message_data.get('url', '')
            message_vals.update({
                'message_type': 'video',
                'content': _('🎥 Video'),
                'attachment_url': video_url,
            })
        
        elif event_name == 'user_send_location':
            # Location sharing
            location = message_data.get('location', {})
            lat = location.get('latitude', '')
            lng = location.get('longitude', '')
            message_vals.update({
                'message_type': 'location',
                'content': f"📍 Location: {lat}, {lng}",
            })
        
        elif event_name == 'oa_send_text':
            # OA sent message to user (outbound from OA dashboard/API)
            message_vals.update({
                'direction': 'outbound',
                'message_type': 'text',
                'content': message_data.get('text', ''),
                'state': 'sent',
            })
            skip_discuss_sync = True
        
        else:
            _logger.warning(f'Unknown event type: {event_name}')
            return
        
        # Create message record
        Message = request.env['zalo.chat.message'].sudo()
        message = Message.create(message_vals)
        
        _logger.info(f'[ZALO WEBHOOK] Created zalo.chat.message id={message.id}, type={message.message_type}')
        
        # Sync to discuss.channel for live chat UI (skip for oa_send_text)
        if not skip_discuss_sync:
            try:
                # Get OA config and livechat channel
                _logger.info(f'[ZALO WEBHOOK] Getting OA config for Live Chat')
                oa_config = request.env['zalo.oa.config'].sudo().search([('active', '=', True)], limit=1)
                
                if not oa_config:
                    _logger.error('[ZALO WEBHOOK] No active OA config found!')
                    return
                
                # Get Live Chat Channel linked to this OA
                livechat_channel = oa_config._get_or_create_livechat_channel()
                _logger.info(f'[ZALO WEBHOOK] Using Live Chat Channel: {livechat_channel.name} ({livechat_channel.id})')
                
                # Find existing session (discuss.channel type=livechat) for this user
                discuss_channel = request.env['discuss.channel'].sudo().search([
                    ('channel_type', '=', 'livechat'),
                    ('livechat_channel_id', '=', livechat_channel.id),
                    ('channel_member_ids.partner_id', '=', conversation.partner_id.id)
                ], limit=1)
                
                if not discuss_channel:
                    _logger.info(f'[ZALO WEBHOOK] Creating new Live Chat session for partner {conversation.partner_id.name}')
                    
                    # Determine operator (required for livechat constraint)
                    operators = livechat_channel.user_ids
                    # Default to current user (admin/system) if no operators configured
                    operator = operators[0] if operators else request.env.user
                    
                    # Create new session with operator
                    discuss_channel = request.env['discuss.channel'].sudo().create({
                        'name': f"{conversation.partner_id.name} (Zalo)",
                        'channel_type': 'livechat',
                        'livechat_channel_id': livechat_channel.id,
                        'livechat_operator_id': operator.partner_id.id,
                        'channel_member_ids': [
                            (0, 0, {'partner_id': conversation.partner_id.id}),
                            (0, 0, {'partner_id': operator.partner_id.id})
                        ]
                    })
                    
                    # Add other operators if any
                    if len(operators) > 1:
                        other_operators = operators[1:]
                        discuss_channel.add_members(partner_ids=other_operators.partner_id.ids)
                else:
                    _logger.info(f'[ZALO WEBHOOK] Found existing session {discuss_channel.id}')
                    
                    # Ensure all active operators are members of the existing session
                    # This fixes the issue where new operators don't see old chats
                    operators = livechat_channel.user_ids
                    if operators:
                         current_member_partners = discuss_channel.channel_partner_ids
                         missing_operators = operators.partner_id - current_member_partners
                         if missing_operators:
                             _logger.info(f'[ZALO WEBHOOK] Adding missing operators {missing_operators.ids} to existing session')
                             discuss_channel.add_members(partner_ids=missing_operators.ids)
                
                # Use this channel for posting
                group_channel = discuss_channel # Alias for compatibility with below code
                
                # Ensure conversation partner is a member (double check)
                if conversation.partner_id and conversation.partner_id not in discuss_channel.channel_partner_ids:
                     discuss_channel.add_members(partner_ids=[conversation.partner_id.id])
                
                if conversation.partner_id:
                    author_id = conversation.partner_id.id
                else:
                    _logger.warning(f'[ZALO WEBHOOK] No partner for conversation {conversation.id}')
                    author_id = False
                
                # Prepare message body with proper HTML rendering
                message_body = message.content or ''
                
                # Render images, videos, and files as HTML
                if message.message_type == 'image' and message.attachment_url:
                    # Just show image, no caption
                    message_body = Markup(f'''
                        <img src="{message.attachment_url}" style="max-width: 400px; max-height: 300px; border-radius: 8px;" />
                    ''')
                elif message.message_type == 'video' and message.attachment_url:
                    message_body = Markup(f'''
                        <p>🎥 Video: <a href="{message.attachment_url}" target="_blank">Click to view</a></p>
                    ''')
                elif message.message_type == 'gif' and message.attachment_url:
                    # Just show GIF, no caption
                    message_body = Markup(f'''
                        <img src="{message.attachment_url}" style="max-width: 400px; max-height: 300px; border-radius: 8px;" />
                    ''')
                elif message.message_type in ['file', 'audio'] and message.attachment_url:
                    # Proxy file download through Odoo to avoid 403
                    proxy_url = f'/zalo/proxy/file?url={message.attachment_url}&msg_id={message.id}'
                    file_name = message.content.replace('📎 File: ', '').replace('🎤 Voice message', 'Audio')
                    message_body = Markup(f'''
                        <p>{message.content}</p>
                        <p><a href="{proxy_url}" target="_blank" class="btn btn-primary btn-sm">
                            <i class="fa fa-download"></i> Download
                        </a></p>
                    ''')
                elif message.message_type == 'link':
                    # Already formatted as text with link in content
                    message_body = Markup(f'<p>{message.content}</p>')
                
                # IMPORTANT: Use context flag to prevent mail.message create hook from
                # sending this message back to Zalo API (would cause infinite loop!)
                _logger.info(f'[ZALO WEBHOOK] Posting message to group channel with skip_zalo_sync=True, author={author_id}')
                group_channel.with_context(skip_zalo_sync=True).message_post(
                    body=message_body,
                    author_id=author_id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )
                
                _logger.info(f'[ZALO WEBHOOK] Synced Zalo message to group channel {group_channel.id}')
            except Exception as e:
                _logger.error(f'[ZALO WEBHOOK] Failed to sync to group channel: {str(e)}', exc_info=True)
        
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

