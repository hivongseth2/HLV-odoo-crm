# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    misa_crm_app_id = fields.Char(
        string='AppID',
        config_parameter='misa_crm.app_id',
        help='AppID bạn đặt khi thiết lập kết nối trong AMIS CRM (Thiết lập → Kết nối → API)',
    )
    misa_crm_secret = fields.Char(
        string='Secret Key',
        config_parameter='misa_crm.secret',
        help='Mã bảo mật dùng để xác thực webhook. Điền vào cả 2 phía: Odoo và AMIS CRM.',
    )
    misa_crm_verify_signature = fields.Boolean(
        string='Xác thực chữ ký (AppID + Secret)',
        config_parameter='misa_crm.verify_signature',
        help='Bật để kiểm tra AppID và Secret trong mọi request webhook. Tắt khi đang debug.',
    )
    misa_crm_auto_create_partner = fields.Boolean(
        string='Tự động tạo khách hàng mới',
        config_parameter='misa_crm.auto_create_partner',
        help='Tự động tạo res.partner nếu chưa tồn tại khi nhận webhook khách hàng.',
    )
    misa_crm_auto_create_order = fields.Boolean(
        string='Tự động tạo đơn hàng mới',
        config_parameter='misa_crm.auto_create_order',
        help='Tự động tạo sale.order nếu chưa tồn tại khi nhận webhook đơn hàng.',
    )

    def action_copy_webhook_url(self):
        """Hiện URL webhook để copy vào AMIS CRM."""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        webhook_url = f'{base_url}/misa/crm/webhook'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('Webhook URL'),
                'message': webhook_url,
                'type':    'info',
                'sticky': True,
            },
        }
