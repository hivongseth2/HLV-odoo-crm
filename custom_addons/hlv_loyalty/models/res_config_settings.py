# -*- coding: utf-8 -*-
from odoo import _, models, fields
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    loyalty_zalo_secret_key = fields.Char(
        string='Zalo App Secret Key',
        config_parameter='hlv_loyalty.zalo_secret_key',
    )
    loyalty_bulk_default_discount = fields.Float(
        string='% chiết khấu mặc định mới',
        digits=(5, 4),
        default=lambda self: self._default_loyalty_bulk_default_discount(),
        help='Nhập dạng thập phân: 0.005 = 0.5%, 0.05 = 5%, 0.1 = 10%.',
    )

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
    loyalty_notification_user_ids = fields.Many2many(
        related='company_id.loyalty_notification_user_ids',
        readonly=False,
        string='Người nhận thông báo Loyalty',
    )
    loyalty_portal_default_password = fields.Char(
        related='company_id.loyalty_portal_default_password',
        readonly=False,
        string='Mật khẩu mặc định Portal',
    )

    def _default_loyalty_bulk_default_discount(self):
        partner = self.env['res.partner'].sudo().with_context(active_test=False).search([
            ('loyalty_default_discount', '>', 0),
        ], limit=1)
        return partner.loyalty_default_discount if partner else 0.05

    def action_update_all_partner_loyalty_default_discount(self):
        self.ensure_one()
        if not self.env.user.has_group('hlv_loyalty.group_loyalty_admin'):
            raise UserError(_('Bạn không có quyền quản trị Loyalty để cập nhật cấu hình này.'))
        if self.loyalty_bulk_default_discount < 0 or self.loyalty_bulk_default_discount > 1:
            raise UserError(_(
                'Tỉ lệ chiết khấu mặc định phải nằm trong khoảng 0 đến 1. '
                'Ví dụ: 0.005 = 0.5%, 0.05 = 5%, 0.1 = 10%.'
            ))

        partners = self.env['res.partner'].sudo().with_context(active_test=False).search([])
        partners.write({'loyalty_default_discount': self.loyalty_bulk_default_discount})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã cập nhật chiết khấu Loyalty mặc định'),
                'message': _(
                    'Đã cập nhật %(count)s khách hàng/liên hệ sang %(rate).2f%%.',
                    count=len(partners),
                    rate=self.loyalty_bulk_default_discount * 100,
                ),
                'type': 'success',
                'sticky': False,
            },
        }
