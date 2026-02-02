# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class ImLivechatChannel(models.Model):
    _inherit = 'im_livechat.channel'

    hlv_ai_enabled = fields.Boolean(
        string='Bật ChatGPT (auto-reply)',
        default=False,
        help=(
            'Nếu bật, tin nhắn từ khách trên Live Chat (website) sẽ được chuyển sang module HLV ChatGPT '
            'và AI sẽ trả lời trực tiếp lại trong cuộc trò chuyện.'
        ),
    )


class HlvChatgptSession(models.Model):
    _inherit = 'hlv.chatgpt.session'

    # Map session <-> livechat conversation (mail.channel)
    mail_channel_id = fields.Many2one('mail.channel', index=True, ondelete='set null')


class MailMessage(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)

        # Post-process each created message. Keep logic best-effort: never break normal message posting.
        for msg in records:
            try:
                self._hlv_maybe_autoreply_livechat(msg)
            except Exception as e:
                _logger.exception('HLV Livechat->ChatGPT bridge error (ignored): %s', e)

        return records

    # -----------------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------------
    def _hlv_maybe_autoreply_livechat(self, msg):
        """Detect inbound visitor messages in livechat channels and auto-reply using hlv_chatgpt."""
        # We only care about messages posted to mail.channel
        if msg.model != 'mail.channel' or not msg.res_id:
            return

        channel = self.env['mail.channel'].sudo().browse(msg.res_id)
        if not channel.exists():
            return

        # Determine whether this mail.channel is a livechat conversation
        # In Odoo, livechat conversations usually have:
        # - channel.channel_type == 'livechat'
        # - and/or channel.livechat_channel_id (Many2one to im_livechat.channel)
        channel_type = getattr(channel, 'channel_type', False)
        livechat_cfg = getattr(channel, 'livechat_channel_id', False)

        if channel_type != 'livechat' and not livechat_cfg:
            return

        # Respect enable flag (only if we can resolve the config channel)
        if livechat_cfg and not livechat_cfg.sudo().hlv_ai_enabled:
            return

        # Ignore our own AI replies to prevent loops
        # If author is a real Odoo user/partner (operator), we also ignore by default
        bot_partner = self.env.user.partner_id
        if msg.author_id and bot_partner and msg.author_id.id == bot_partner.id:
            return

        # Heuristic: only reply to visitor/public messages.
        # In many setups, visitor messages are created with author_id=False or author as "Visitor" partner.
        # If there is an author with a linked user, treat as operator and ignore.
        if msg.author_id and msg.author_id.user_ids:
            return

        # Extract plaintext
        body = html2plaintext(msg.body or '').strip()
        if not body:
            return

        # Find or create a ChatGPT session for this mail.channel
        session = self.env['hlv.chatgpt.session'].sudo().search(
            [('mail_channel_id', '=', channel.id)],
            order='last_activity desc',
            limit=1,
        )
        if not session:
            # Use channel name as topic; keep it safe/short
            session = self.env['hlv.chatgpt.session'].sudo().create({
                'name': (channel.display_name or 'Live Chat')[:128],
                'state': 'active',
                'mail_channel_id': channel.id,
            })

        # Persist message into hlv.chatgpt.message history
        self.env['hlv.chatgpt.message'].sudo().create({
            'session_id': session.id,
            'role': 'user',
            'content': body,
        })
        session.sudo().write({
            'last_customer_message': body,
        })

        # Call OpenAI
        ai_reply = session._call_openai_api(body)
        ai_reply = (ai_reply or '').strip() or '...'

        # Save summary/memory fields
        session.sudo().write({
            'last_ai_reply': ai_reply,
            'last_activity': fields.Datetime.now(),
        })
        session._update_session_summary(body, ai_reply)

        self.env['hlv.chatgpt.message'].sudo().create({
            'session_id': session.id,
            'role': 'assistant',
            'content': ai_reply,
        })

        # Post reply back to the livechat channel
        # NOTE: message_post uses current env user as author; that's OK for now.
        channel.sudo().message_post(
            body=ai_reply,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

        _logger.info('✅ Livechat auto-replied via ChatGPT | channel=%s | msg_id=%s', channel.id, msg.id)
