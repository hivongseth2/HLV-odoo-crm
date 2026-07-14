# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

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
        if is_chatter_message and is_delete_request:
            raise UserError(
                _(
                    "Không được xóa nội dung đã ghi trong chatter. "
                    "Các trao đổi và lịch sử thay đổi phải được giữ lại để đối soát."
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
