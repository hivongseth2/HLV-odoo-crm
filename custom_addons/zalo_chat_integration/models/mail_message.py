# -*- coding: utf-8 -*-

from odoo import models, api, fields, _
import logging

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
                    zalo_message = self.env['zalo.chat.message'].sudo().create({
                        'conversation_id': conversation.id,
                        'direction': 'outbound',
                        'message_type': 'text',
                        'content': message.body,
                        'state': 'draft',
                    })
                    
                    # Send via Zalo API
                    zalo_message.action_send()
                    
                    _logger.info(f'Sent message from discuss.channel to Zalo: {zalo_message.id}')
                    
                except Exception as e:
                    _logger.error(f'Failed to send message to Zalo: {str(e)}', exc_info=True)
        
        return messages
