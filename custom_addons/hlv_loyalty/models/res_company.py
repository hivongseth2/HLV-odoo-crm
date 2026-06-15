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
    loyalty_notification_user_ids = fields.Many2many(
        'res.users',
        'res_company_hlv_loyalty_notification_user_rel',
        'company_id',
        'user_id',
        string='Người nhận thông báo Loyalty',
        help='Các user nội bộ nhận bus notification khi có yêu cầu đổi thưởng hoặc khách đổi quà.',
    )
    loyalty_portal_default_password = fields.Char(
        string='Mật khẩu mặc định Portal',
        default='hlv@2026',
        help='Mật khẩu mặc định khi tạo tài khoản Portal Loyalty mới. Tối thiểu 6 ký tự.',
    )
