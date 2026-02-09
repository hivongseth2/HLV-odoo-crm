from odoo import models, api, _, tools
from odoo.exceptions import UserError
import logging
import json
import re
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'
    
    def _find_or_create_member_for_self(self):
        """
        Override to handle member creation for chat channels gracefully
        """
        if self.channel_type == 'chat':
            # Check if current user is already a member
            current_partner = self.env.user.partner_id
            existing_member = self.env['discuss.channel.member'].search([
                ('channel_id', '=', self.id),
                ('partner_id', '=', current_partner.id)
            ], limit=1)
            
            if existing_member:
                return existing_member
            else:
                # Try to create member, catch the UserError about limit
                try:
                    return super(DiscussChannel, self)._find_or_create_member_for_self()
                except UserError as e:
                    error_msg = str(e)
                    if 'cannot add more members' in error_msg.lower() or 'không thể thêm nhiều thành viên' in error_msg.lower():
                        _logger.debug(
                            f'Cannot add user {current_partner.id} to chat channel {self.id} '
                            f'(member limit reached), returning first existing member'
                        )
                        # Return any existing member to avoid NotFound error
                        return self.channel_member_ids[0] if self.channel_member_ids else self.env['discuss.channel.member']
                    else:
                        raise
        
        return super(DiscussChannel, self)._find_or_create_member_for_self()
    
    def add_members(self, partner_ids=None, guest_ids=None, **kwargs):
        """
        Override to prevent adding new members to chat channels
        """
        if self.channel_type == 'chat':
            # Check current member count
            current_member_count = len(self.channel_partner_ids)
            if current_member_count >= 2:
                # Filter out partners that are not already members
                if partner_ids:
                    existing_partner_ids = self.channel_partner_ids.ids
                    filtered_partner_ids = [pid for pid in partner_ids if pid in existing_partner_ids]
                    if not filtered_partner_ids:
                        _logger.debug(
                            f'Blocked add_members for chat channel {self.id} '
                            f'(already has {current_member_count} members)'
                        )
                        # Return existing members
                        return self.channel_member_ids
                    partner_ids = filtered_partner_ids
        
        return super(DiscussChannel, self).add_members(partner_ids=partner_ids, guest_ids=guest_ids, **kwargs)
    
    def write(self, vals):
        """
        Override write to prevent adding members to chat channels
        IMPORTANT: Only filter channel_partner_ids, NOT other fields like avatar_128
        """
        # Only process if trying to modify members
        if 'channel_partner_ids' in vals:
            for channel in self:
                if channel.channel_type == 'chat':
                    # Check if trying to add new members
                    commands = vals.get('channel_partner_ids', [])
                    current_partner_ids = set(channel.channel_partner_ids.ids)
                    
                    # Filter out commands that would add new members
                    filtered_commands = []
                    for cmd in commands:
                        if cmd[0] == 4:  # Link existing partner
                            if cmd[1] not in current_partner_ids:
                                _logger.debug(
                                    f'Blocked attempt to add partner {cmd[1]} to '
                                    f'chat channel {channel.id} (already has 2 members)'
                                )
                                continue
                        elif cmd[0] == 0:  # Create new member
                            partner_id = cmd[2].get('partner_id')
                            if partner_id and partner_id not in current_partner_ids:
                                _logger.debug(
                                    f'Blocked attempt to add partner {partner_id} to '
                                    f'chat channel {channel.id} (already has 2 members)'
                                )
                                continue
                        filtered_commands.append(cmd)
                    
                    # Update vals with filtered commands
                    vals['channel_partner_ids'] = filtered_commands
        
        # Suppress UserError for chat channel member limit
        try:
            result = super(DiscussChannel, self).write(vals)
            
            # Debug logging for avatar writes
            if 'avatar_128' in vals:
                for channel in self:
                    _logger.info(f'[WRITE DEBUG] Channel {channel.id} - avatar_128 written: {bool(vals.get("avatar_128"))} ({len(vals.get("avatar_128", b""))} bytes)')
                    # Verify after write
                    _logger.info(f'[WRITE DEBUG] Channel {channel.id} - avatar_128 after write: {bool(channel.avatar_128)} ({len(channel.avatar_128) if channel.avatar_128 else 0} bytes)')
            
            return result
        except UserError as e:
            error_msg = str(e)
            if 'cannot add more members' in error_msg.lower() or 'không thể thêm nhiều thành viên' in error_msg.lower():
                _logger.debug(f'Suppressed member limit error for chat channel: {error_msg}')
                # Return True to indicate success without actually writing invalid data
                return True
            else:
                raise
    
    def message_post(self, **kwargs):
        """
        Override to prevent auto-adding author to chat channels
        when posting messages (which causes 'too many members' error)
        
        Also intercept outbound messages to send via Zalo API
        """
        # _logger.info(f'[ZALO DEBUG] discuss.channel.message_post called for channel {self.id}, type={self.channel_type}')
        
        # SLASH COMMAND INTERCEPTION (Check FIRST to prevent sending to customer)
        message_body = kwargs.get('body', '')
        if message_body and message_body.strip().lower() == '/baogia':
             _logger.info(f'[ZALO SLASH] Detected /baogia command. Executing Logic...')
             
             # 1. Post command to Odoo Chat (Internal Note or Comment? Keep as comment so user sees it)
             # But explicitly SKIP Zalo Sync for this message
             ctx = dict(self.env.context)
             ctx['skip_zalo_sync'] = True
             res = super(DiscussChannel, self.with_context(ctx)).message_post(**kwargs)
             
             # 2. Trigger AI Actions
             try:
                 # Create Quote
                 self.action_gpt_create_quote()
                 
                 # UPDATE SUMMARY (New Request)
                 self.action_gpt_update_customer_profile()
                 
             except Exception as e:
                 _logger.error(f"Error executing /baogia: {e}")
                 self.message_post(body=f"⚠️ Lỗi: {str(e)}", message_type='notification', subtype_xmlid='mail.mt_note')
             
             return res

        # SLASH COMMAND /checkton
        if message_body and message_body.strip().lower() == '/checkton':
             _logger.info(f'[ZALO SLASH] Detected /checkton command. Executing Logic...')
             
             # 1. Post command to Odoo Chat (SKIP Zalo Sync)
             ctx = dict(self.env.context)
             ctx['skip_zalo_sync'] = True
             res = super(DiscussChannel, self.with_context(ctx)).message_post(**kwargs)
             
             # 2. Trigger AI Stock Check
             try:
                 self.action_gpt_check_stock()
             except Exception as e:
                 _logger.error(f"Error executing /checkton: {e}")
                 self.message_post(body=f"⚠️ Lỗi: {str(e)}", message_type='notification', subtype_xmlid='mail.mt_note')
             
             return res

        # For chat type channels (1-to-1), disable auto-adding author
        if self.channel_type == 'chat':
            # Check if we're trying to post from a partner not in the channel
            author_id = kwargs.get('author_id')
            if author_id:
                # Check if author is already a member
                partner_ids = self.channel_partner_ids.ids
                if author_id not in partner_ids:
                    # Partner not in channel - log debug but don't add
                    # _logger.debug(f'Posting to chat channel {self.id} from non-member {author_id} as system message')
                    # Post as system message instead (no author)
                    kwargs['author_id'] = False
        
        # INTERCEPT OUTBOUND MESSAGES (Re-implementation for Odoo 18)
        try:
            # Check context to avoid recursion
            if not self.env.context.get('skip_zalo_sync'):
                
                # Check if Live Chat Channel linked to Zalo
                if self.channel_type == 'livechat' and self.livechat_channel_id:
                    # _logger.info(f'[ZALO DEBUG] Channel {self.id} is livechat, linked to {self.livechat_channel_id.id}')
                    
                    oa_config = self.env['zalo.oa.config'].sudo().search([
                        ('livechat_channel_id', '=', self.livechat_channel_id.id)
                    ], limit=1)
                    
                    if oa_config:
                        # _logger.info(f'[ZALO DEBUG] Found OA Config {oa_config.oa_name} for channel {self.id}')
                        
                        # Filtering: Only send 'comment' messages, SKIP 'notification'
                        message_type = kwargs.get('message_type', 'comment')
                        if message_type != 'comment':
                            # _logger.info(f'[ZALO DEBUG] Skipping outbound message type: {message_type}')
                            return super(DiscussChannel, self).message_post(**kwargs)

                        # Filtering: Block specific system keywords if any leaked as comment
                        if message_body and ('Đã tạo báo giá' in str(message_body) or '🤖 AI:' in str(message_body)):
                             _logger.info(f'[ZALO DEBUG] Skipping System/AI notification')
                             return super(DiscussChannel, self).message_post(**kwargs)
                             
                        # author_id might be in kwargs or from context
                        author_id = kwargs.get('author_id') or self.env.user.partner_id.id
                        
                        if message_body:
                            # Find Zalo Conversation
                            target_partner = False
                            for partner in self.channel_partner_ids:
                                if partner.id != author_id:
                                    target_partner = partner
                                    break
                            
                            if target_partner:
                                conv = self.env['zalo.chat.conversation'].sudo().search([
                                    ('partner_id', '=', target_partner.id)
                                ], limit=1)
                                
                                if conv:
                                    plain_text = tools.html2plaintext(message_body)
                                    if plain_text and plain_text.strip():
                                        # DEDUPLICATION CHECK: Prevent double-send from UI
                                        last_sent = self.env['zalo.chat.message'].sudo().search([
                                            ('conversation_id', '=', conv.id),
                                            ('direction', '=', 'outbound'),
                                            ('content', '=', plain_text),
                                            ('create_date', '>=', fields.Datetime.now() - datetime.timedelta(seconds=2))
                                        ], limit=1)
                                        
                                        if last_sent:
                                             _logger.warning(f'[ZALO OUTBOUND] Duplicate send detected for {conv.id}, skipping.')
                                             return super(DiscussChannel, self).message_post(**kwargs)

                                        zalo_message = self.env['zalo.chat.message'].sudo().create({
                                            'conversation_id': conv.id,
                                            'direction': 'outbound',
                                            'message_type': 'text',
                                            'content': plain_text,
                                            'state': 'draft',
                                        })
                                        
                                        _logger.info(f'[ZALO OUTBOUND] Sending message {zalo_message.id} to {target_partner.name}')
                                        zalo_message.action_send()
                                        
                                        # IMPORTANT: Prevent double-sending if super check isn't enough?
                                        # Currently we just call action_send() which calls API.
                                        # We do NOT return here, we let super() create the Odoo message.
                                    else:
                                        pass
                                else:
                                    _logger.warning(f'[ZALO DEBUG] No Zalo conversation found for partner {target_partner.name}')
                            else:
                                _logger.warning(f'[ZALO DEBUG] Could not identify target partner in channel {self.id}')
                    else:
                        pass
                        # No OA Config

        except Exception as e:
            _logger.error(f'[ZALO ERROR] Error in message_post intercept: {str(e)}', exc_info=True)

        return super(DiscussChannel, self).message_post(**kwargs)

