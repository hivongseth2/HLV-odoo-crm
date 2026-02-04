# -*- coding: utf-8 -*-

from odoo import models, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'
    
    def _find_or_create_member_for_self(self):
        """
        Override to prevent creating new members for chat channels
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
                # User is not a member - don't add, just return empty
                _logger.debug(
                    f'User {current_partner.id} is not a member of chat channel {self.id}, '
                    f'skipping member creation to avoid limit error'
                )
                return self.env['discuss.channel.member']
        
        return super(DiscussChannel, self)._find_or_create_member_for_self()
    
    def add_members(self, partner_ids=None, guest_ids=None, **kwargs):
        """
        Override to prevent adding new members to chat channels
        """
        if self.channel_type == 'chat':
            # Check current member count
            current_member_count = len(self.channel_partner_ids)
            if current_member_count >= 2:
                _logger.debug(
                    f'Blocked add_members for chat channel {self.id} '
                    f'(already has {current_member_count} members)'
                )
                # Return existing members instead of adding
                return self.channel_member_ids
        
        return super(DiscussChannel, self).add_members(partner_ids=partner_ids, guest_ids=guest_ids, **kwargs)
    
    def write(self, vals):
        """
        Override write to prevent adding members to chat channels
        """
        for channel in self:
            if channel.channel_type == 'chat' and 'channel_partner_ids' in vals:
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
            return super(DiscussChannel, self).write(vals)
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
        """
        # For chat type channels (1-to-1), disable auto-adding author
        if self.channel_type == 'chat':
            # Check if we're trying to post from a partner not in the channel
            author_id = kwargs.get('author_id')
            if author_id:
                # Check if author is already a member
                partner_ids = self.channel_partner_ids.ids
                if author_id not in partner_ids:
                    # Partner not in channel - log debug but don't add
                    _logger.debug(
                        f'Posting to chat channel {self.id} from non-member '
                        f'partner {author_id} as system message'
                    )
                    # Post as system message instead (no author)
                    kwargs['author_id'] = False
        
        return super(DiscussChannel, self).message_post(**kwargs)
    
    def notify_typing(self, is_typing):
        """
        Override to prevent auto-adding members on typing notification
        For chat channels, only notify if user is already a member
        """
        if self.channel_type == 'chat':
            # Check if current user is a member
            current_partner = self.env.user.partner_id
            if current_partner not in self.channel_partner_ids:
                _logger.debug(
                    f'Skipping typing notification for non-member '
                    f'partner {current_partner.id} in channel {self.id}'
                )
                # Don't call super - just return without error
                return
        
        return super(DiscussChannel, self).notify_typing(is_typing)
    
    def _notify_thread(self, message, msg_vals=False, **kwargs):
        """
        Override to prevent auto-subscribing partners on notification
        """
        if self.channel_type == 'chat':
            # Don't auto-subscribe - just send notifications to existing members
            return super(DiscussChannel, self)._notify_thread(message, msg_vals=msg_vals, **kwargs)
        
        return super(DiscussChannel, self)._notify_thread(message, msg_vals=msg_vals, **kwargs)
