# -*- coding: utf-8 -*-
from odoo import fields, models


class MailMessage(models.Model):
    _inherit = "mail.message"

    # Một tài khoản Odoo nhiều sale dùng chung, nên tác giả tin không nói được ai nhắn. Trang
    # /hoi-gia-ncc ghi lại mã sale đang chọn lúc gửi để trao đổi hiện "ai" theo mã sale.
    hlv_sale_code = fields.Char(string="Mã sale gửi", readonly=True, copy=False)
