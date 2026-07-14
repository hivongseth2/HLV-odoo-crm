# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.mail.controllers.thread import ThreadController

from ..models.mail_message import DELETE_CHATTER_MESSAGE_GROUP


class HlvThreadController(ThreadController):

    @http.route()
    def mail_message_update_content(
        self,
        message_id,
        body,
        attachment_ids,
        attachment_tokens=None,
        partner_ids=None,
        **kwargs,
    ):
        is_delete_request = body == "" and attachment_ids == []
        if (
            is_delete_request
            and request.env.user.has_group(DELETE_CHATTER_MESSAGE_GROUP)
        ):
            request.update_context(hlv_allow_chatter_message_delete=True)
        return super().mail_message_update_content(
            message_id,
            body,
            attachment_ids,
            attachment_tokens=attachment_tokens,
            partner_ids=partner_ids,
            **kwargs,
        )

    def _is_message_editable(self, message, **kwargs):
        is_chatter_message = (
            message.model
            and message.res_id
            and message.model not in ("discuss.channel", "mail.channel")
        )
        if (
            is_chatter_message
            and request.env.context.get("hlv_allow_chatter_message_delete")
            and request.env.user.has_group(DELETE_CHATTER_MESSAGE_GROUP)
        ):
            return True
        return super()._is_message_editable(message, **kwargs)
