# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
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
    
    zalo_user_id = fields.Char(
        string='Zalo User ID',
        required=True,
        copy=False,
        tracking=True,
        help='ID người dùng Zalo',
    )
    
    zalo_user_name = fields.Char(
        string='Tên người dùng',
        tracking=True,
        help='Tên hiển thị của người dùng Zalo',
    )
    
    zalo_avatar = fields.Char(
        string='Avatar URL',
        help='URL avatar của người dùng Zalo',
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Liên hệ',
        tracking=True,
        help='Liên hệ Odoo được liên kết với người dùng Zalo này',
    )
    
    message_ids = fields.One2many(
        'zalo.chat.message',
        'conversation_id',
        string='Tin nhắn',
    )
    
    state = fields.Selection([
        ('open', 'Đang mở'),
        ('closed', 'Đã đóng'),
        ('archived', 'Đã lưu trữ'),
    ], string='Trạng thái', default='open', required=True, tracking=True,
       help='Trạng thái của hội thoại')
    
    last_message_date = fields.Datetime(
        string='Tin nhắn cuối',
        compute='_compute_last_message_date',
        store=True,
        help='Thời gian tin nhắn cuối cùng',
    )
    
    unread_count = fields.Integer(
        string='Chưa đọc',
        compute='_compute_unread_count',
        help='Số tin nhắn chưa đọc',
    )
    
    discuss_channel_id = fields.Many2one(
        'discuss.channel',
        string='Kênh Chat',
        help='Kênh Discuss được liên kết để hiển thị live chat',
        readonly=True,
    )
    
    @api.depends('message_ids.sent_date')
    def _compute_last_message_date(self):
        for conversation in self:
            if conversation.message_ids:
                conversation.last_message_date = max(
                    conversation.message_ids.mapped('sent_date')
                )
            else:
                conversation.last_message_date = False
    
    @api.depends('message_ids.is_read', 'message_ids.direction')
    def _compute_unread_count(self):
        for conversation in self:
            conversation.unread_count = len(
                conversation.message_ids.filtered(
                    lambda m: m.direction == 'inbound' and not m.is_read
                )
            )
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                # Generate sequence
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'zalo.chat.conversation'
                ) or _('New')
        
        conversations = super(ZaloChatConversation, self).create(vals_list)
        
        for conversation in conversations:
            # Auto-link partner if exists
            if not conversation.partner_id and conversation.zalo_user_id:
                partner = self.env['res.partner'].search([
                    ('zalo_user_id', '=', conversation.zalo_user_id)
                ], limit=1)
                if partner:
                    conversation.partner_id = partner
        
        return conversations
    
    def action_close(self):
        self.write({'state': 'closed'})
    
    def action_reopen(self):
        self.write({'state': 'open'})
    
    def action_create_evaluation(self):
        """Create a new evaluation record for this conversation"""
        self.ensure_one()
        
        # Get chat content from stored messages
        messages = self.message_ids.sorted(key=lambda m: m.sent_date)
        content_lines = []
        for msg in messages:
            sender = "Khách" if msg.direction == 'inbound' else "NV"
            content = msg.content or "[File/Image]"
            content_lines.append(f"{sender} ({msg.sent_date}): {content}")
            
        chat_content = "\n".join(content_lines)
        
        channel = self._get_active_livechat_channel()
        
        evaluation = self.env['zalo.chat.evaluation'].create({
            'partner_id': self.partner_id.id,
            'conversation_id': self.id,
            'chat_content': chat_content,
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Đánh giá hội thoại',
            'res_model': 'zalo.chat.evaluation',
            'res_id': evaluation.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_send_message(self):
        """Open wizard to send message"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Gửi tin nhắn Zalo',
            'res_model': 'send.zalo.chat.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_conversation_id': self.id,
                'default_recipient_id': self.zalo_user_id,
            },
        }
    
    def action_open_chat(self):
        """Open Live Chat session for this conversation"""
        self.ensure_one()
        
        if not self.partner_id:
             return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi',
                    'message': 'Không tìm thấy Partner liên kết với hội thoại này. Vui lòng chờ tin nhắn đầu tiên để hệ thống tự tạo.',
                    'type': 'danger',
                }
            }
            
        # Search for existing Live Chat session
        # Logic: discuss.channel type='livechat', member=self.partner_id
        domain = [
            ('channel_type', '=', 'livechat'),
            ('channel_member_ids.partner_id', '=', self.partner_id.id)
        ]
        # Sort by updated desc to get latest session
        channel = self.env['discuss.channel'].sudo().search(domain, order='write_date desc', limit=1)
        
        if channel:
            return {
                'type': 'ir.actions.client',
                'tag': 'mail.action_discuss',
                'params': {
                    'active_id': channel.id,
                }
            }
            
        # If no session found
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Chưa có phiên chat',
                'message': 'Chưa có phiên Live Chat nào cho khách hàng này. Phiên chat sẽ tự động tạo khi có tin nhắn mới từ khách hàng.',
                'type': 'warning',
            }
        }
    
    @api.model
    def action_open_all_zalo_chats(self):
        """
        Open list of Live Chat sessions linked to active Zalo OAs.
        If no OA config, redirect to configuration.
        """
        configs = self.env['zalo.oa.config'].sudo().search([('active', '=', True)])
        
        if not configs:
            # Check if action exists before returning
            action = self.env.ref('zalo_chat_integration.action_zalo_oa_config', raise_if_not_found=False)
            if action:
                return action.read()[0]
            return False
        
        livechat_ids = []
        for config in configs:
            # Ensure livechat channel exists
            lc = config._get_or_create_livechat_channel()
            livechat_ids.append(lc.id)
            
        return {
            'type': 'ir.actions.act_window',
            'name': 'Kênh Zalo OA',
            'res_model': 'im_livechat.channel',
            'view_mode': 'kanban,form',
            'domain': [('id', 'in', livechat_ids)],
            'help': """
                <p class="o_view_nocontent_smiling_face">
                    Chưa có kênh Zalo OA nào được cấu hình Live Chat.
                </p>
                <p>
                    Vui lòng vào Cấu hình Zalo OA để thiết lập.
                </p>
            """
        }


    def _get_active_livechat_channel(self):
        """Helper to find the associated livechat channel"""
        self.ensure_one()
        if not self.partner_id:
            return None
            
        domain = [
            ('channel_type', '=', 'livechat'),
            ('channel_member_ids.partner_id', '=', self.partner_id.id)
        ]
        # Sort by updated desc to get latest session
        return self.env['discuss.channel'].sudo().search(domain, order='write_date desc', limit=1)

    def action_gpt_summarize(self):
        """Proxy to channel action"""
        channel = self._get_active_livechat_channel()
        if not channel:
             raise UserError(_("Chưa tìm thấy phiên Live Chat nào."))
        return channel.action_gpt_summarize()
        
    def action_gpt_create_quote(self):
        """Proxy to channel action"""
        channel = self._get_active_livechat_channel()
        if not channel:
             raise UserError(_("Chưa tìm thấy phiên Live Chat nào."))
        return channel.action_gpt_create_quote()



