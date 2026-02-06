# -*- coding: utf-8 -*-

from odoo import models, api, fields, _
import logging
import re

_logger = logging.getLogger(__name__)


class MailMessage(models.Model):
    _inherit = 'mail.message'
    
    @api.model_create_multi
    def create(self, vals_list):
        """
        Hook để sync messages từ discuss.channel về Zalo
        
        Khi user gửi tin nhắn trong discuss widget → gửi qua Zalo API
        """
        messages = super().create(vals_list)
        
        # CRITICAL: Skip if this is a message from webhook (already synced from Zalo)
        # This prevents infinite loop: Zalo → webhook → channel.message_post → mail.message.create → Zalo
        if self.env.context.get('skip_zalo_sync'):
            _logger.info(f'[ZALO DEBUG] Skipping all messages - skip_zalo_sync context is True (from webhook)')
            return messages
        
        for message in messages:
            # DEBUG: Log all messages being processed
            _logger.info(f'[ZALO DEBUG] Processing mail.message id={message.id}, model={message.model}, res_id={message.res_id}, type={message.message_type}, author_id={message.author_id.id if message.author_id else None}')
            
            # Only process messages in discuss.channel
            if message.model == 'discuss.channel' and message.res_id:
                # NEW LOGIC: Check if this is a Zalo Group Channel
                # Logic: Is this channel linked to any Zalo OA config? 
                # Or check channel type='channel' and name starts with ZALO OA (less reliable)
                
                conversation = False
                
                # Method 1: Check Live Chat Channel (New Architecture)
                channel = self.env['discuss.channel'].sudo().browse(message.res_id)
                if channel.channel_type == 'livechat' and channel.livechat_channel_id:
                    # Check if this Live Chat belongs to Zalo
                    oa_config = self.env['zalo.oa.config'].sudo().search([('livechat_channel_id', '=', channel.livechat_channel_id.id)], limit=1)
                    
                    if oa_config:
                        _logger.info(f'[ZALO OUTBOUND] Message in Zalo Live Chat Session {channel.id}')
                        
                        # Find recipient (Zalo Customer)
                        # The recipient is the member who has a Zalo Conversation linked
                        for partner in channel.channel_partner_ids:
                            # Skip if partner is the author (operator)
                            if partner == message.author_id:
                                continue
                                
                            conv = self.env['zalo.chat.conversation'].sudo().search([
                                ('partner_id', '=', partner.id)
                            ], limit=1)
                            
                            if conv:
                                conversation = conv
                                break
                        
                        if not conversation:
                             _logger.warning(f'[ZALO OUTBOUND] Could not find Zalo Conversation for any partner in Live Chat session {channel.id}')

                # Method 2: Legacy individual channel support
                if not conversation:
                    conversation = self.env['zalo.chat.conversation'].sudo().search([
                        ('discuss_channel_id', '=', message.res_id)
                    ], limit=1)
                
                if not conversation:
                    # Not a Zalo channel
                    continue
                
                _logger.info(f'[ZALO DEBUG] Found conversation id={conversation.id}, partner={conversation.partner_id.id if conversation.partner_id else None}')
                
                # Skip if message is from Zalo user (inbound already processed)
                if message.author_id == conversation.partner_id:
                    _logger.info(f'[ZALO DEBUG] Skipping - message from Zalo user (inbound)')
                    continue
                
                # Skip system messages - but allow attachments!
                if message.message_type != 'comment':
                    _logger.info(f'[ZALO DEBUG] Skipping - not a comment type: {message.message_type}')
                    continue
                    
                # Skip if no content AND no attachments
                if not message.body and not message.attachment_ids:
                    _logger.info(f'[ZALO DEBUG] Skipping - no body and no attachments')
                    continue
                
                # Skip if this is a notification we posted ourselves
                if 'Tin nhắn mới từ' in (message.body or ''):
                    _logger.info(f'[ZALO DEBUG] Skipping - notification message')
                    continue
                
                # Handle Group Channel special case:
                # If message is in group channel, but intended for Zalo user, 
                # we don't need to post "Tin nhắn mới từ..." back to the channel because it's already there!
                # Unless we want to confirm sending? No, keep it clean.
                
                _logger.info(f'[ZALO DEBUG] SENDING to Zalo: body={bool(message.body)}, body_preview={str(message.body)[:50] if message.body else None}, attachments={len(message.attachment_ids)}')
                
                try:
                    # User sent message in discuss → send to Zalo
                    # NO member adding here - members already set on channel creation
                    
                    # Check if message has attachments
                    if message.attachment_ids:
                        _logger.info(f'[ZALO DEBUG] Processing {len(message.attachment_ids)} attachment(s)')
                        # Process attachments (images, files)
                        for attachment in message.attachment_ids:
                            try:
                                self._send_attachment_to_zalo(attachment, conversation)
                            except Exception as e:
                                _logger.error(
                                    f'Failed to send attachment {attachment.id} to Zalo: {str(e)}',
                                    exc_info=True
                                )
                    
                    # Process text content if any
                    if message.body and message.body.strip():
                        # Strip HTML tags from message body
                        plain_text = self._strip_html(message.body)
                        
                        # Only send if there's actual text content
                        if plain_text and plain_text.strip():
                            _logger.info(f'[ZALO DEBUG] Creating zalo.chat.message for text: "{plain_text[:50]}"')
                            
                            zalo_message = self.env['zalo.chat.message'].sudo().create({
                                'conversation_id': conversation.id,
                                'direction': 'outbound',
                                'message_type': 'text',
                                'content': plain_text,
                                'state': 'draft',
                            })
                            
                            # Send via Zalo API
                            zalo_message.action_send()
                            
                            _logger.info(f'[ZALO DEBUG] SENT zalo.chat.message id={zalo_message.id}')
                    
                except Exception as e:
                    _logger.error(f'Failed to send message to Zalo: {str(e)}', exc_info=True)
        
        return messages
    
    def _send_attachment_to_zalo(self, attachment, conversation):
        """
        Send attachment (image or file) to Zalo via API
        
        Zalo API Limitations:
        - Files: max 1MB, only pdf/doc/docx/csv supported
        - Images: max 1MB, jpg/png/gif supported
        """
        import base64
        import requests
        
        # Get Zalo config
        config = self.env['zalo.oa.config'].sudo().get_active_config()
        access_token = config._check_token_validity()
        
        # Read attachment data
        file_data = base64.b64decode(attachment.datas)
        filename = attachment.name
        mimetype = attachment.mimetype or 'application/octet-stream'
        file_size = len(file_data)
        
        _logger.info(f'Sending attachment to Zalo: {filename} ({mimetype}, {file_size} bytes)')
        
        # Determine if image or file
        is_image = mimetype.startswith('image/')
        
        # === VALIDATION ===
        # Check file size (Zalo limit: 1MB = 1048576 bytes)
        MAX_SIZE = 1048576  # 1MB
        if file_size > MAX_SIZE:
            error_msg = f'❌ File "{filename}" quá lớn ({file_size // 1024}KB). Zalo chỉ cho phép tối đa 1MB.'
            _logger.warning(error_msg)
            # Post notification to chat
            self._post_upload_error(conversation, error_msg)
            return
        
        # Check file type for non-images
        if not is_image:
            ALLOWED_EXTENSIONS = ['.pdf', '.doc', '.docx', '.csv']
            file_ext = '.' + filename.split('.')[-1].lower() if '.' in filename else ''
            
            if file_ext not in ALLOWED_EXTENSIONS:
                error_msg = f'❌ File "{filename}" không được hỗ trợ. Zalo chỉ cho phép: PDF, DOC, DOCX, CSV'
                _logger.warning(error_msg)
                self._post_upload_error(conversation, error_msg)
                return
        
        # Check image type
        if is_image:
            ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/jpg']
            if mimetype not in ALLOWED_IMAGE_TYPES:
                error_msg = f'❌ Ảnh "{filename}" không được hỗ trợ. Zalo chỉ cho phép: JPG, PNG, GIF'
                _logger.warning(error_msg)
                self._post_upload_error(conversation, error_msg)
                return
        
        # === UPLOAD ===
        if is_image:
            url = 'https://openapi.zalo.me/v2.0/oa/upload/image'
        else:
            url = 'https://openapi.zalo.me/v2.0/oa/upload/file'
        
        files = {'file': (filename, file_data, mimetype)}
        headers = {'access_token': access_token}
        
        _logger.info(f'Uploading to Zalo API: {url}')
        response = requests.post(url, headers=headers, files=files, timeout=60)
        
        _logger.info(f'Zalo upload response: {response.status_code} - {response.text[:500]}')
        
        if response.status_code != 200:
            error_msg = f'❌ Lỗi upload "{filename}": HTTP {response.status_code}'
            _logger.error(error_msg)
            self._post_upload_error(conversation, error_msg)
            return
        
        result = response.json()
        
        if result.get('error') != 0:
            error_code = result.get('error')
            error_message = result.get('message', 'Unknown error')
            error_msg = f'❌ Lỗi Zalo API ({error_code}): {error_message}'
            _logger.error(error_msg)
            self._post_upload_error(conversation, error_msg)
            return
        
        data = result.get('data', {})
        attachment_id = data.get('attachment_id')
        token = data.get('token')
        
        # Validation based on type
        if is_image and not attachment_id:
            error_msg = f'❌ Zalo không trả về attachment_id cho ảnh "{filename}"'
            _logger.error(f'{error_msg}. Full response: {result}')
            self._post_upload_error(conversation, error_msg)
            return
            
        if not is_image and not token:
            error_msg = f'❌ Zalo không trả về token cho file "{filename}"'
            _logger.error(f'{error_msg}. Full response: {result}')
            self._post_upload_error(conversation, error_msg)
            return
        
        _logger.info(f'✓ Uploaded to Zalo. ID/Token: {attachment_id or token}')
        
        # Now send message with attachment
        send_url = 'https://openapi.zalo.me/v3.0/oa/message/cs'
        
        if is_image:
            payload = {
                'recipient': {'user_id': conversation.zalo_user_id},
                'message': {
                    'attachment': {
                        'type': 'template',
                        'payload': {
                            'template_type': 'media',
                            'elements': [{
                                'media_type': 'image',
                                'attachment_id': attachment_id,
                            }],
                        },
                    },
                },
            }
        else:
            # File sending uses token
            payload = {
                'recipient': {'user_id': conversation.zalo_user_id},
                'message': {
                    'attachment': {
                        'type': 'file',
                        'payload': {
                            'token': token,
                        },
                    },
                },
            }
        
        send_response = requests.post(
            send_url,
            headers={'access_token': access_token, 'Content-Type': 'application/json'},
            json=payload,
            timeout=30
        )
        
        if send_response.status_code != 200:
            raise Exception(f'Zalo send API error {send_response.status_code}: {send_response.text}')
        
        send_result = send_response.json()
        
        if send_result.get('error') != 0:
            raise Exception(f'Zalo send API error {send_result.get("error")}: {send_result.get("message")}')
        
        _logger.info(f'✓ Sent {filename} to Zalo successfully!')
        
        # Create zalo.chat.message record
        self.env['zalo.chat.message'].sudo().create({
            'conversation_id': conversation.id,
            'direction': 'outbound',
            'message_type': 'image' if is_image else 'file',
            'content': f'📎 {filename}',
            'attachment_url': attachment_id,  # Store Zalo attachment_id
            'state': 'sent',
        })
    
    def _strip_html(self, html):
        """Strip HTML tags and decode entities"""
        if not html:
            return ''
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', html)
        
        # Decode HTML entities
        import html as html_lib
        text = html_lib.unescape(text)
        
        return text.strip()
    
    def _post_upload_error(self, conversation, error_msg):
        """
        Post error message to the discuss channel to notify user
        """
        from markupsafe import Markup
        
        try:
            # Find the active livechat session for this conversation's partner
            # Logic matches action_open_chat
            if not conversation.partner_id:
                _logger.warning('No partner linked to conversation, cannot post error.')
                return

            domain = [
                ('channel_type', '=', 'livechat'),
                ('channel_member_ids.partner_id', '=', conversation.partner_id.id)
            ]
            # Get latest session
            channel = self.env['discuss.channel'].sudo().search(domain, order='write_date desc', limit=1)
            
            if channel:
                # Post error as plain text (safe, no HTML issues)
                channel.sudo().message_post(
                    body=Markup(f'<p style="color: red; font-weight: bold;">⚠️ {error_msg}</p>'),
                    message_type='notification',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id
                )
                _logger.info(f'Posted upload error notification to channel {channel.id}')
            else:
                 _logger.warning(f'Could not find active Live Chat session to post error for partner {conversation.partner_id.name}')
        except Exception as e:
            _logger.error(f'Failed to post upload error: {str(e)}')
