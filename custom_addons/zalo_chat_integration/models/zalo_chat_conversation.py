# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ZaloChatConversation(models.Model):
    _name = 'zalo.chat.conversation'
    _description = 'Hội thoại Zalo Chat'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'last_message_date desc, id desc'

    name = fields.Char(
        string='Hội thoại',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Liên hệ',
        tracking=True,
        help='Liên hệ Odoo được liên kết với người dùng Zalo này',
    )
    zalo_user_id = fields.Char(
        string='ID người dùng Zalo',
        required=True,
        index=True,
        help='Mã định danh duy nhất của người dùng Zalo từ webhook',
    )
    zalo_user_name = fields.Char(
        string='Tên người dùng',
        help='Tên hiển thị của người dùng Zalo',
    )
    zalo_avatar = fields.Char(
        string='Ảnh đại diện',
        help='URL ảnh đại diện người dùng Zalo',
    )
    message_ids = fields.One2many(
        'zalo.chat.message',
        'conversation_id',
        string='Tin nhắn',
    )
    last_message_date = fields.Datetime(
        string='Tin nhắn cuối',
        compute='_compute_last_message_date',
        store=True,
        help='Thời gian của tin nhắn gần nhất',
    )
    state = fields.Selection([
        ('open', 'Đang mở'),
        ('closed', 'Đã đóng'),
        ('archived', 'Lưu trữ'),
    ], string='Trạng thái', default='open', required=True, tracking=True)
    
    unread_count = fields.Integer(
        string='Chưa đọc',
        compute='_compute_unread_count',
        help='Số tin nhắn đến chưa đọc',
    )
    discuss_channel_id = fields.Many2one(
        'discuss.channel',
        string='Kênh chat',
        help='Kênh discuss liên kết với hội thoại Zalo này',
        ondelete='cascade',
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
    
    def _get_or_create_discuss_channel(self):
        """
        Tạo hoặc lấy discuss.channel cho conversation này
        Dùng cho live chat UI
        """
        self.ensure_one()
        
        if self.discuss_channel_id:
            return self.discuss_channel_id
        
        # Create unique channel name
        if self.partner_id:
            channel_name = f"Zalo: {self.partner_id.name}"
        elif self.zalo_user_name and self.zalo_user_name != 'Zalo User':
            channel_name = f"Zalo: {self.zalo_user_name}"
        else:
            # Use last 4 digits of Zalo ID for uniqueness
            short_id = self.zalo_user_id[-4:] if len(self.zalo_user_id) > 4 else self.zalo_user_id
            channel_name = f"Zalo User #{short_id}"
        
        # Create private channel
        channel_vals = {
            'name': channel_name,
            'channel_type': 'chat',  # 1-to-1 chat
            'description': f'Chat với Zalo user {self.zalo_user_id}',
        }
        
        # Add current user as member
        channel_vals['channel_member_ids'] = [
            (0, 0, {
                'partner_id': self.env.user.partner_id.id,
            })
        ]
        
        # Link to partner if exists
        if self.partner_id:
            channel_vals['channel_member_ids'].append(
                (0, 0, {
                    'partner_id': self.partner_id.id,
                })
            )
        
        channel = self.env['discuss.channel'].create(channel_vals)
        
        self.discuss_channel_id = channel.id
        
        _logger.info(f'Created discuss.channel {channel.id} for Zalo conversation {self.id}')
        
        return channel
    
    def action_open_chat(self):
        """Open Discuss app with this channel active"""
        self.ensure_one()
        channel = self._get_or_create_discuss_channel()
        
        # Redirect to Discuss app with channel selected
        return {
            'type': 'ir.actions.client',
            'tag': 'mail.action_discuss',
            'params': {
                'default_active_id': f'mail.box_inbox',
                'active_id': channel.id,
            },
            'context': {
                'active_id': channel.id,
            },
        }

    @api.model
    def _find_or_create_conversation(self, zalo_user_id, user_info=None):
        """
        Find existing conversation or create new one for Zalo user
        Auto-fetch user info from Zalo API if not provided
        """
        conversation = self.search([('zalo_user_id', '=', zalo_user_id)], limit=1)
        
        if not conversation:
            # Fetch user info from Zalo if not provided
            if not user_info:
                user_info = self._fetch_zalo_user_info(zalo_user_id)
            
            # Create new conversation
            vals = {
                'zalo_user_id': zalo_user_id,
                'zalo_user_name': user_info.get('display_name') or user_info.get('user_name') or 'Zalo User',
                'zalo_avatar': user_info.get('avatar'),
                'state': 'open',
            }
            
            # Auto-create partner if we have useful info
            if user_info.get('display_name') or user_info.get('user_name'):
                partner = self._get_or_create_partner(zalo_user_id, user_info)
                vals['partner_id'] = partner.id
            
            conversation = self.create(vals)
            _logger.info(f'Created new Zalo conversation for user {zalo_user_id}')
        
        return conversation
