# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError

from .guard_context import parent_thread_unlink


DELETE_CHATTER_MESSAGE_GROUP = (
    "hlv_chatter_delivery_guard.group_delete_chatter_message"
)


class MailMessage(models.Model):
    _inherit = "mail.message"

    def _hlv_user_can_delete_chatter_message(self):
        return self.env.user.has_group(DELETE_CHATTER_MESSAGE_GROUP)

    def unlink(self):
        protected_messages = self.filtered(
            lambda message: message.model
            and message.res_id
            and message.model not in ("discuss.channel", "mail.channel")
        )
        if (
            protected_messages
            and not parent_thread_unlink.get()
            and not self._hlv_user_can_delete_chatter_message()
        ):
            raise UserError(
                _(
                    "Không được xóa nội dung đã ghi trong chatter. "
                    "Bạn chưa được cấp quyền Xóa tin nhắn chatter."
                )
            )
        return super().unlink()
