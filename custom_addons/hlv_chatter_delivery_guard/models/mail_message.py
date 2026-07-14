# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class MailMessage(models.Model):
    _inherit = "mail.message"

    def unlink(self):
        protected_messages = self.filtered(
            lambda message: message.model
            and message.res_id
            and message.model not in ("discuss.channel", "mail.channel")
        )
        if protected_messages:
            raise UserError(
                _(
                    "Không được xóa nội dung đã ghi trong chatter. "
                    "Các trao đổi và lịch sử thay đổi phải được giữ lại để đối soát."
                )
            )
        return super().unlink()
