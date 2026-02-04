# -*- coding: utf-8 -*-

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'
    
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
                    # Partner not in channel - log warning but don't add
                    _logger.warning(
                        f'Attempting to post to chat channel {self.id} from '
                        f'non-member partner {author_id}. Message will be posted '
                        f'as system message to avoid member limit error.'
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
