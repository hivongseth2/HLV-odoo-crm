# -*- coding: utf-8 -*-
from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    loyalty_program_id = fields.Many2one(
        'hlv.loyalty.program', string='Chương trình Loyalty mặc định',
        help='Chương trình tích điểm mặc định cho công ty',
    )
    loyalty_allow_manual_adjust = fields.Boolean(
        string='Cho phép điều chỉnh điểm thủ công', default=False,
        help='Cho phép nhân viên điều chỉnh điểm loyalty thủ công',
    )
    loyalty_send_notification = fields.Boolean(
        string='Gửi thông báo tích điểm', default=True,
        help='Gửi email/thông báo cho khách khi được tích điểm',
    )
    loyalty_portal_default_password = fields.Char(
        string='Mật khẩu mặc định Portal',
        default='hlv@2026',
        help='Mật khẩu mặc định khi tạo tài khoản Portal Loyalty mới. Tối thiểu 6 ký tự.',
    )
