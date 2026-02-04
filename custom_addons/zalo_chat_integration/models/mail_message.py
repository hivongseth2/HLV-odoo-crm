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
        
        for message in messages:
            # Only process messages in discuss.channel
            if message.model == 'discuss.channel' and message.res_id:
                # Find Zalo conversation linked to this channel
                conversation = self.env['zalo.chat.conversation'].sudo().search([
                    ('discuss_channel_id', '=', message.res_id)
                ], limit=1)
                
                if not conversation:
                    continue
                
                # Skip if message is from Zalo user (inbound already processed)
                if message.author_id == conversation.partner_id:
                    continue
                
                # Skip system messages
                if message.message_type != 'comment' or not message.body:
                    continue
                
                # Skip if this is a notification we posted ourselves
                if 'Tin nhắn mới từ' in (message.body or ''):
                    continue
                
                try:
                    # User sent message in discuss → send to Zalo
                    # NO member adding here - members already set on channel creation
                    
                    # Check if message has attachments
                    if message.attachment_ids:
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
                            zalo_message = self.env['zalo.chat.message'].sudo().create({
                                'conversation_id': conversation.id,
                                'direction': 'outbound',
                                'message_type': 'text',
                                'content': plain_text,
                                'state': 'draft',
                            })
                            
                            # Send via Zalo API
                            zalo_message.action_send()
                            
                            _logger.info(f'Sent text message from discuss.channel to Zalo: {zalo_message.id}')
                    
                except Exception as e:
                    _logger.error(f'Failed to send message to Zalo: {str(e)}', exc_info=True)
        
        return messages
    
    def _send_attachment_to_zalo(self, attachment, conversation):
        """
        Send attachment (image or file) to Zalo via API
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
        
        _logger.info(f'Sending attachment to Zalo: {filename} ({mimetype}, {len(file_data)} bytes)')
        
        # Determine if image or file
        is_image = mimetype.startswith('image/')
        
        if is_image:
            # Upload image
            url = 'https://openapi.zalo.me/v2.0/oa/upload/image'
        else:
            # Upload file  
            url = 'https://openapi.zalo.me/v2.0/oa/upload/file'
        
        # Upload to Zalo
        files = {'file': (filename, file_data, mimetype)}
        headers = {'access_token': access_token}
        
        response = requests.post(url, headers=headers, files=files, timeout=60)
        
        if response.status_code != 200:
            raise Exception(f'Zalo upload API error {response.status_code}: {response.text}')
        
        result = response.json()
        
        if result.get('error') != 0:
            raise Exception(f'Zalo API error {result.get("error")}: {result.get("message")}')
        
        attachment_id = result.get('data', {}).get('attachment_id')
        
        if not attachment_id:
            raise Exception(f'No attachment_id returned from Zalo upload')
        
        _logger.info(f'✓ Uploaded to Zalo, attachment_id: {attachment_id}')
        
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
            payload = {
                'recipient': {'user_id': conversation.zalo_user_id},
                'message': {
                    'attachment': {
                        'type': 'file',
                        'payload': {
                            'attachment_id': attachment_id,
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
