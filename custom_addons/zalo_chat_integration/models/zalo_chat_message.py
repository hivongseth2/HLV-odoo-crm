# -*- coding: utf-8 -*-

import requests
import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class ZaloChatMessage(models.Model):
    _name = 'zalo.chat.message'
    _description = 'Zalo Chat Message'
    _order = 'sent_date desc, id desc'

    conversation_id = fields.Many2one(
        'zalo.chat.conversation',
        string='Conversation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    partner_id = fields.Many2one(
        related='conversation_id.partner_id',
        string='Contact',
        store=True,
        readonly=True,
    )
    message_id = fields.Char(
        string='Zalo Message ID',
        help='Unique message identifier from Zalo',
        index=True,
    )
    direction = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ], string='Direction', required=True, default='outbound')
    
    message_type = fields.Selection([
        ('text', 'Text'),
        ('image', 'Image'),
        ('sticker', 'Sticker'),
        ('file', 'File'),
        ('audio', 'Audio'),
        ('video', 'Video'),
        ('location', 'Location'),
    ], string='Type', required=True, default='text')
    
    content = fields.Text(
        string='Message Content',
        help='Text content of the message',
    )
    attachment_url = fields.Char(
        string='Attachment URL',
        help='URL of attached file/image',
    )
    attachment_type = fields.Char(
        string='Attachment MIME Type',
    )
    sent_date = fields.Datetime(
        string='Sent Date',
        default=fields.Datetime.now,
        required=True,
    )
    is_read = fields.Boolean(
        string='Read',
        default=False,
        help='Whether this inbound message has been read',
    )
    error_message = fields.Text(
        string='Error Details',
        help='Error message if sending failed',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    ], string='Status', default='draft', required=True)

    def action_send(self):
        """Send the message via Zalo API"""
        for message in self:
            if message.direction != 'outbound':
                raise UserError(_('Only outbound messages can be sent!'))
            
            if message.state == 'sent':
                raise UserError(_('This message has already been sent!'))
            
            try:
                # Get Zalo config from zalo_zns module
                config = self.env['zalo.zns.config'].search([], limit=1)
                if not config:
                    raise UserError(_('Zalo configuration not found. Please configure Zalo ZNS first.'))
                
                if not config.access_token:
                    raise UserError(_('No access token available. Please authorize Zalo first.'))
                
                # Prepare payload
                payload = message._prepare_zalo_payload()
                
                # Call Zalo API
                response = message._call_zalo_send_api(config, payload)
                
                # Update message state
                message.write({
                    'state': 'sent',
                    'sent_date': fields.Datetime.now(),
                })
                
                # Post to conversation chatter
                message.conversation_id.message_post(
                    body=Markup(_('<b>Message sent:</b> %s')) % (message.content or _('(attachment)')),
                )
                
                _logger.info(f'Zalo message sent successfully: {message.id}')
                
            except Exception as e:
                error_msg = str(e)
                message.write({
                    'state': 'failed',
                    'error_message': error_msg,
                })
                
                # Post error to chatter
                message.conversation_id.message_post(
                    body=Markup(_('<div style="color: red;"><b>Failed to send message:</b> %s</div>')) % error_msg,
                )
                
                _logger.error(f'Failed to send Zalo message {message.id}: {error_msg}')
                raise UserError(_('Failed to send message: %s') % error_msg)

    def _prepare_zalo_payload(self):
        """Prepare JSON payload for Zalo send message API"""
        self.ensure_one()
        
        payload = {
            'recipient': {
                'user_id': self.conversation_id.zalo_user_id,
            },
        }
        
        if self.message_type == 'text':
            payload['message'] = {
                'text': self.content or '',
            }
        elif self.message_type == 'image':
            if not self.attachment_url:
                raise UserError(_('Image URL is required for image messages!'))
            payload['message'] = {
                'attachment': {
                    'type': 'template',
                    'payload': {
                        'template_type': 'media',
                        'elements': [{
                            'media_type': 'image',
                            'url': self.attachment_url,
                        }],
                    },
                },
            }
        elif self.message_type == 'file':
            if not self.attachment_url:
                raise UserError(_('File URL is required for file messages!'))
            payload['message'] = {
                'attachment': {
                    'type': 'file',
                    'payload': {
                        'url': self.attachment_url,
                    },
                },
            }
        else:
            raise UserError(_('Message type %s is not yet supported for sending!') % self.message_type)
        
        return payload

    def _call_zalo_send_api(self, config, payload):
        """
        Call Zalo OA Message API to send message
        
        :param config: zalo.zns.config record
        :param payload: Dict - message payload
        :return: API response dict
        """
        self.ensure_one()
        
        url = 'https://openapi.zalo.me/v3.0/oa/message/cs'
        headers = {
            'access_token': config.access_token,
            'Content-Type': 'application/json',
        }
        
        _logger.info(f'Sending Zalo message API call: {json.dumps(payload)}')
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code != 200:
            raise UserError(
                _('Zalo API returned error %s: %s') % (response.status_code, response.text)
            )
        
        result = response.json()
        
        # Check Zalo API response
        if result.get('error') != 0:
            raise UserError(
                _('Zalo API error %s: %s') % (result.get('error'), result.get('message'))
            )
        
        return result

    @api.model
    def cron_sync_message_status(self):
        """
        Cron job to sync message delivery status from Zalo
        (Placeholder for future implementation)
        """
        _logger.info('Zalo message status sync cron running...')
        # TODO: Implement status checking if Zalo provides such API
        return True
