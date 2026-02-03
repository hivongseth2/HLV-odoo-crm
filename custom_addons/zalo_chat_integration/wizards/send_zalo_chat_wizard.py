# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SendZaloChatWizard(models.TransientModel):
    _name = 'send.zalo.chat.wizard'
    _description = 'Send Zalo Chat Message Wizard'

    conversation_id = fields.Many2one(
        'zalo.chat.conversation',
        string='Conversation',
        required=True,
        readonly=True,
    )
    message_type = fields.Selection([
        ('text', 'Text Message'),
        ('image', 'Image'),
        ('file', 'File'),
    ], string='Message Type', default='text', required=True)
    
    message_content = fields.Text(
        string='Message',
        help='Text content to send',
    )
    attachment_file = fields.Binary(
        string='Attachment',
        help='File or image to send',
    )
    attachment_filename = fields.Char(
        string='Filename',
    )

    @api.onchange('message_type')
    def _onchange_message_type(self):
        """Clear fields when changing message type"""
        if self.message_type == 'text':
            self.attachment_file = False
            self.attachment_filename = False
        else:
            self.message_content = False

    def action_send(self):
        """Send the message"""
        self.ensure_one()
        
        # Validate input
        if self.message_type == 'text' and not self.message_content:
            raise UserError(_('Please enter a message!'))
        
        if self.message_type in ('image', 'file') and not self.attachment_file:
            raise UserError(_('Please select a file to send!'))
        
        # Prepare message values
        message_vals = {
            'conversation_id': self.conversation_id.id,
            'direction': 'outbound',
            'message_type': self.message_type,
            'state': 'draft',
        }
        
        if self.message_type == 'text':
            message_vals['content'] = self.message_content
        
        else:
            # For image/file, we need to upload to a server first
            # This is a simplified version - in production, you'd upload to your server
            # or use Zalo's upload API
            raise UserError(_(
                'File/Image sending is not yet fully implemented.\n'
                'You need to:\n'
                '1. Upload the file to a publicly accessible server\n'
                '2. Use the URL in the message API call\n\n'
                'For now, please use text messages only.'
            ))
        
        # Create and send message
        Message = self.env['zalo.chat.message']
        message = Message.create(message_vals)
        message.action_send()
        
        return {'type': 'ir.actions.act_window_close'}
