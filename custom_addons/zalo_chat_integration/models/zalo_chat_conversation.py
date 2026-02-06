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
    
    def _get_or_create_discuss_channel(self):
        """
        Tạo hoặc lấy discuss.channel cho conversation này
        Dùng cho live chat UI
        """
        self.ensure_one()
        
        if self.discuss_channel_id:
            return self.discuss_channel_id
        
        # Create unique channel name
        # NOTE: Do NOT use "Zalo:" prefix - it breaks avatar lookup in Odoo
        # Odoo chat channels use partner name for avatar display
        if self.partner_id:
            channel_name = self.partner_id.name
        elif self.zalo_user_name and self.zalo_user_name != 'Zalo User':
            channel_name = self.zalo_user_name
        else:
            # Use last 4 digits of Zalo ID for uniqueness
            short_id = self.zalo_user_id[-4:] if len(self.zalo_user_id) > 4 else self.zalo_user_id
            channel_name = f"Zalo User #{short_id}"
        
        # Ensure we have a partner for the Zalo user
        if not self.partner_id:
            # Fetch user info and create partner
            user_info = self._fetch_zalo_user_info(self.zalo_user_id)
            if user_info:
                partner = self._get_or_create_partner(self.zalo_user_id, user_info)
                self.partner_id = partner.id
                # Update conversation name
                if user_info.get('display_name') or user_info.get('user_name'):
                    self.zalo_user_name = user_info.get('display_name') or user_info.get('user_name')
                    channel_name = self.zalo_user_name  # Use name directly, no prefix
        
        # Create private channel (chat type automatically handles 2 members limit)
        channel_vals = {
            'name': channel_name,
            'channel_type': 'chat',  # 1-to-1 chat
            'description': f'Chat với Zalo user {self.zalo_user_id}',
        }
        
        # For chat type, use channel_partner_ids instead of channel_member_ids
        # This avoids the "too many members" error
        partners = [self.env.user.partner_id.id]
        if self.partner_id:
            partners.append(self.partner_id.id)
        
        channel_vals['channel_partner_ids'] = [(4, pid) for pid in partners]
        
        channel = self.env['discuss.channel'].create(channel_vals)
        
        self.discuss_channel_id = channel.id
        
        # Set channel avatar explicitly from partner
        if self.partner_id and self.partner_id.image_128:
            try:
                channel.sudo().write({
                    'image_128': self.partner_id.image_128
                })
                _logger.info(f'Set avatar for channel {channel.id} from partner {self.partner_id.id}')
            except Exception as e:
                _logger.warning(f'Failed to set channel avatar: {e}')
        
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
    def action_open_all_zalo_chats(self):
        """Open Discuss app showing all Zalo channels"""
        # Ensure all conversations have discuss channels
        conversations = self.search([])
        for conv in conversations:
            conv._get_or_create_discuss_channel()
        
        # Open Discuss app
        return {
            'type': 'ir.actions.client',
            'tag': 'mail.action_discuss',
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
                _logger.info(f'Fetching user info from Zalo API for new user {zalo_user_id}')
                user_info = self._fetch_zalo_user_info(zalo_user_id)
            
            # Create new conversation
            vals = {
                'zalo_user_id': zalo_user_id,
                'zalo_user_name': user_info.get('display_name') or user_info.get('user_alias') or 'Zalo User',
                'zalo_avatar': user_info.get('avatar'),
                'state': 'open',
            }
            
            # Auto-create partner if we have useful info
            if user_info.get('display_name') or user_info.get('user_alias'):
                partner = self._get_or_create_partner(zalo_user_id, user_info)
                vals['partner_id'] = partner.id
            
            conversation = self.create(vals)
            _logger.info(f'Created new Zalo conversation for user {zalo_user_id}: {vals.get("zalo_user_name")}')
        else:
            _logger.debug(f'Found existing conversation for Zalo user {zalo_user_id}')
        
        return conversation
    
    def _fetch_zalo_user_info(self, zalo_user_id):
        """
        Fetch user information from Zalo API
        Returns dict with display_name, user_name, avatar
        """
        try:
            config = self.env['zalo.oa.config'].get_active_config()
            access_token = config._check_token_validity()
            
            url = 'https://openapi.zalo.me/v3.0/oa/user/detail'
            headers = {
                'access_token': access_token,
                'Content-Type': 'application/json',
            }
            
            payload = {
                'user_id': zalo_user_id,
            }
            
            import requests
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            result = response.json()
            
            if result.get('error') == 0:
                data = result.get('data', {})
                _logger.info(f'Fetched Zalo user info for {zalo_user_id}: {data.get("display_name")}')
                return data
            else:
                _logger.warning(f'Failed to fetch Zalo user info: {result.get("message")}')
                return {}
        
        except Exception as e:
            _logger.error(f'Error fetching Zalo user info: {str(e)}', exc_info=True)
            return {}
    
    def _get_or_create_partner(self, zalo_user_id, user_info):
        """
        Get or create partner for Zalo user
        Uses full API response including shared_info
        Downloads and saves avatar image
        """
        from psycopg2.errors import UniqueViolation
        
        Partner = self.env['res.partner']
        
        # Search existing partner
        partner = Partner.search([('zalo_user_id', '=', zalo_user_id)], limit=1)
        
        if partner:
            return partner
        
        # Prepare partner values
        name = user_info.get('display_name') or user_info.get('user_alias') or f'Zalo User {zalo_user_id[-4:]}'
        partner_vals = {
            'name': name,
            'zalo_user_id': zalo_user_id,
        }
        
        # Get shared_info if available
        shared_info = user_info.get('shared_info', {})
        
        # Add phone from shared_info or user_id_by_app
        phone = shared_info.get('phone') or user_info.get('user_id_by_app')
        if phone and str(phone) != '0':
            partner_vals['phone'] = str(phone)
        
        # Add address info if available
        if shared_info.get('address'):
            partner_vals['street'] = shared_info.get('address')
        
        if shared_info.get('city'):
            partner_vals['city'] = shared_info.get('city')
        
        # Download and save avatar
        avatar_url = user_info.get('avatar')
        if not avatar_url and user_info.get('avatars'):
            # Try to get from avatars dict (prefer 240px)
            avatars = user_info.get('avatars', {})
            avatar_url = avatars.get('240') or avatars.get('120')
        
        if avatar_url:
            avatar_data = self._download_avatar(avatar_url)
            if avatar_data:
                partner_vals['image_1920'] = avatar_data
        
        try:
            partner = Partner.create(partner_vals)
            _logger.info(f'Created partner for Zalo user: {name} (ID: {zalo_user_id})')
        except Exception as e:
            # Handle race condition - another process created the partner
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                self.env.cr.rollback()
                partner = Partner.search([('zalo_user_id', '=', zalo_user_id)], limit=1)
                if partner:
                    _logger.info(f'Found existing partner after UniqueViolation: {partner.name}')
                    return partner
            raise
        
        return partner
    
    def _download_avatar(self, url):
        """
        Download avatar image from URL and return base64 encoded data
        """
        try:
            import requests
            import base64
            
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                # Encode to base64
                avatar_base64 = base64.b64encode(response.content)
                _logger.info(f'Downloaded avatar from {url}')
                return avatar_base64
            else:
                _logger.warning(f'Failed to download avatar: HTTP {response.status_code}')
                return None
        
        except Exception as e:
            _logger.error(f'Error downloading avatar: {str(e)}')
            return None

