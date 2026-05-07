# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    loyalty_program_id = fields.Many2one(
        related='company_id.loyalty_program_id',
        readonly=False,
        string='Chương trình Loyalty mặc định',
    )
    loyalty_allow_manual_adjust = fields.Boolean(
        related='company_id.loyalty_allow_manual_adjust',
        readonly=False,
        string='Cho phép điều chỉnh điểm thủ công',
    )
    loyalty_send_notification = fields.Boolean(
        related='company_id.loyalty_send_notification',
        readonly=False,
        string='Gửi thông báo tích điểm',
    )
