# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ZaloChatConversation(models.Model):
    _name = 'zalo.chat.conversation'
    _description = 'Zalo Chat Conversation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'last_message_date desc, id desc'

    name = fields.Char(
        string='Conversation',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        tracking=True,
        help='Linked Odoo contact for this Zalo user',
    )
    zalo_user_id = fields.Char(
        string='Zalo User ID',
        required=True,
        index=True,
        help='Unique Zalo user identifier from webhook',
    )
    zalo_user_name = fields.Char(
        string='Zalo User Name',
        help='Display name of the Zalo user',
    )
    zalo_avatar = fields.Char(
        string='Avatar URL',
        help='Zalo user avatar image URL',
    )
    message_ids = fields.One2many(
        'zalo.chat.message',
        'conversation_id',
        string='Messages',
    )
    last_message_date = fields.Datetime(
        string='Last Message',
        compute='_compute_last_message_date',
        store=True,
        help='Timestamp of the most recent message',
    )
    state = fields.Selection([
        ('open', 'Open'),
        ('closed', 'Closed'),
        ('archived', 'Archived'),
    ], string='Status', default='open', required=True, tracking=True)
    
    unread_count = fields.Integer(
        string='Unread Messages',
        compute='_compute_unread_count',
        help='Number of unread inbound messages',
    )

    _sql_constraints = [
        ('zalo_user_id_unique', 'UNIQUE(zalo_user_id)', 
         'A conversation already exists for this Zalo user!'),
    ]

    @api.model
    def create(self, vals):
        """Auto-generate conversation name from sequence"""
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code(
                'zalo.chat.conversation'
            ) or _('New')
        return super().create(vals)

    @api.depends('message_ids.sent_date')
    def _compute_last_message_date(self):
        """Compute last message timestamp"""
        for conversation in self:
            last_message = conversation.message_ids.sorted(
                'sent_date', reverse=True
            )[:1]
            conversation.last_message_date = (
                last_message.sent_date if last_message else False
            )

    def _compute_unread_count(self):
        """Count unread inbound messages"""
        for conversation in self:
            conversation.unread_count = self.env['zalo.chat.message'].search_count([
                ('conversation_id', '=', conversation.id),
                ('direction', '=', 'inbound'),
                ('is_read', '=', False),
            ])

    def action_send_message(self):
        """Open wizard to send a message"""
        self.ensure_one()
        return {
            'name': _('Send Zalo Message'),
            'type': 'ir.actions.act_window',
            'res_model': 'send.zalo.chat.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_conversation_id': self.id,
            },
        }

    def action_mark_as_read(self):
        """Mark all messages in this conversation as read"""
        self.ensure_one()
        unread_messages = self.message_ids.filtered(
            lambda m: m.direction == 'inbound' and not m.is_read
        )
        unread_messages.write({'is_read': True})
        return True

    def action_close(self):
        """Close the conversation"""
        self.write({'state': 'closed'})

    def action_reopen(self):
        """Reopen a closed conversation"""
        self.write({'state': 'open'})

    @api.model
    def _find_or_create_conversation(self, zalo_user_id, user_info=None):
        """
        Find existing conversation or create new one for a Zalo user
        
        :param zalo_user_id: Zalo user ID
        :param user_info: Dict with keys: name, avatar (optional)
        :return: zalo.chat.conversation recordset
        """
        conversation = self.search([('zalo_user_id', '=', zalo_user_id)], limit=1)
        
        if not conversation:
            vals = {
                'zalo_user_id': zalo_user_id,
            }
            if user_info:
                vals.update({
                    'zalo_user_name': user_info.get('name', ''),
                    'zalo_avatar': user_info.get('avatar', ''),
                })
            
            # Try to find existing partner with this Zalo ID
            partner = self.env['res.partner'].search([
                ('zalo_user_id', '=', zalo_user_id)
            ], limit=1)
            if partner:
                vals['partner_id'] = partner.id
            
            conversation = self.create(vals)
            _logger.info(f'Created new Zalo conversation for user {zalo_user_id}')
        
        return conversation
