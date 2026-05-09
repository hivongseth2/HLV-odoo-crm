# -*- coding: utf-8 -*-
from odoo import models, fields, exceptions


class HlvLoyaltyResetPasswordWizard(models.TransientModel):
    _name = 'hlv.loyalty.reset.password.wizard'
    _description = 'Wizard reset mật khẩu Portal Loyalty'

    account_id = fields.Many2one(
        'hlv.loyalty.portal.account', string='Tài khoản', required=True,
    )
    new_password = fields.Char(string='Mật khẩu mới', required=True)
    confirm_password = fields.Char(string='Xác nhận mật khẩu', required=True)

    def action_confirm(self):
        if self.new_password != self.confirm_password:
            raise exceptions.UserError('Mật khẩu xác nhận không khớp.')
        self.account_id.reset_password(self.new_password)
        return {'type': 'ir.actions.act_window_close'}
