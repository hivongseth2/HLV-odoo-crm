# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ─── Credentials ───────────────────────────────────────────────────────────
    meinvoice_environment = fields.Selection(
        selection=[('sandbox', 'Sandbox (test)'), ('production', 'Production')],
        string='Môi trường',
        default='sandbox',
        config_parameter='meinvoice.environment',
        required=True,
    )
    meinvoice_app_id = fields.Char(
        string='App ID',
        config_parameter='meinvoice.app_id',
        help='App ID do MISA cung cấp',
    )
    meinvoice_tax_code = fields.Char(
        string='Mã số thuế',
        config_parameter='meinvoice.tax_code',
    )
    meinvoice_username = fields.Char(
        string='Tài khoản (email / SĐT)',
        config_parameter='meinvoice.username',
    )
    meinvoice_password = fields.Char(
        string='Mật khẩu',
        config_parameter='meinvoice.password',
    )

    # ─── Invoice defaults ──────────────────────────────────────────────────────
    meinvoice_inv_series = fields.Char(
        string='Ký hiệu hóa đơn mặc định',
        config_parameter='meinvoice.inv_series',
        help='Ví dụ: 1K24TAA',
    )
    meinvoice_invoice_name = fields.Char(
        string='Tên hóa đơn mặc định',
        config_parameter='meinvoice.invoice_name',
        default='Hóa đơn giá trị gia tăng',
        config_parameter_field='meinvoice.invoice_name',
    )
    meinvoice_auto_publish = fields.Boolean(
        string='Tự động phát hành khi xác nhận hóa đơn',
        config_parameter='meinvoice.auto_publish',
    )

    def action_test_meinvoice_connection(self):
        self.ensure_one()
        # Lưu trước khi test
        self.execute()
        ok, msg = self.env['meinvoice.api'].api_test_connection()
        if ok:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('MEinvoice'),
                    'message': msg,
                    'type': 'success',
                    'sticky': False,
                },
            }
        raise UserError(msg)
