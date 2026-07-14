# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError

from .guard_context import parent_thread_unlink
from .mail_message import DELETE_CHATTER_MESSAGE_GROUP


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def unlink(self):
        # Core mail.thread.unlink() removes all linked messages before deleting
        # the document. Mark only that server-side call chain as allowed so a
        # client cannot forge an Odoo context value to bypass the guard.
        token = parent_thread_unlink.set(True)
        try:
            return super().unlink()
        finally:
            parent_thread_unlink.reset(token)

    def _message_update_content(
        self,
        message,
        /,
        *,
        body,
        attachment_ids=None,
        partner_ids=None,
        strict=True,
        **kwargs,
    ):
        # In Odoo 18 the chatter Delete action does not unlink mail.message.
        # It calls /mail/message/update_content with an empty body and an empty
        # attachment list, which makes the message disappear from the thread.
        is_chatter_message = (
            message.model
            and message.res_id
            and message.model not in ("discuss.channel", "mail.channel")
        )
        is_delete_request = body == "" and attachment_ids == []
        can_delete_message = self.env.user.has_group(DELETE_CHATTER_MESSAGE_GROUP)
        if is_chatter_message and is_delete_request and not can_delete_message:
            raise UserError(
                _(
                    "Không được xóa nội dung đã ghi trong chatter. "
                    "Bạn chưa được cấp quyền Xóa tin nhắn chatter."
                )
            )
        return super()._message_update_content(
            message,
            body=body,
            attachment_ids=attachment_ids,
            partner_ids=partner_ids,
            strict=strict,
            **kwargs,
        )
