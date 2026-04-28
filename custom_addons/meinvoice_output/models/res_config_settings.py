# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    meinvoice_output_environment = fields.Selection(
        [('sandbox', 'Sandbox (test)'), ('production', 'Production')],
        string='Môi trường',
        config_parameter='meinvoice_output.environment',
        default='sandbox',
    )
    meinvoice_output_client_id = fields.Char(
        'ClientID', config_parameter='meinvoice_output.client_id',
        help='ClientID do MISA cung cấp',
    )
    meinvoice_output_app_id = fields.Char(
        'AppID', config_parameter='meinvoice_output.app_id',
        help='AppID do MISA cung cấp',
    )
    meinvoice_output_tax_code = fields.Char(
        'Mã số thuế', config_parameter='meinvoice_output.tax_code',
    )
    meinvoice_output_username = fields.Char(
        'Tài khoản', config_parameter='meinvoice_output.username',
    )
    meinvoice_output_password = fields.Char(
        'Mật khẩu', config_parameter='meinvoice_output.password',
    )

    def action_test_meinvoice_output_connection(self):
        self.ensure_one()
        self.execute()
        ok, msg = self.env['meinvoice.output.api'].api_test_connection()
        if ok:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': _('meInvoice'), 'message': msg,
                           'type': 'success', 'sticky': False},
            }
        raise UserError(msg)
