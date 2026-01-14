# -*- coding: utf-8 -*-
from odoo import fields, models, api
from ..utils.jt_api_utils import JTApiUtils

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    jt_customer_code = fields.Char(
        related="company_id.jt_customer_code",
        readonly=False,
        string="Mã khách hàng J&T (Customer Code)",
    )
    jt_password = fields.Char(
        related="company_id.jt_password",
        readonly=False,
        string="Mật khẩu J&T (Password)",
    )
    jt_environment = fields.Selection(
        related="company_id.jt_environment",
        readonly=False,
        string="Môi trường J&T",
    )

    # Read-only display fields for credentials from System Parameters
    jt_api_account_display = fields.Char(
        string="J&T apiAccount (từ System Param)",
        compute="_compute_jt_credentials",
    )
    jt_private_key_display = fields.Char(
        string="J&T privateKey (từ System Param)",
        compute="_compute_jt_credentials",
    )

    def _compute_jt_credentials(self):
        get_param = self.env['ir.config_parameter'].sudo().get_param
        for record in self:
            record.jt_api_account_display = get_param('jnt_apiAccount') or 'Chưa cấu hình jnt_apiAccount'
            record.jt_private_key_display = get_param('jnt_privateKey') or 'Chưa cấu hình jnt_privateKey'

    def action_check_jt_connection(self):
        """Test connection to J&T API"""
        get_param = self.env['ir.config_parameter'].sudo().get_param
        api_account = get_param('jnt_apiAccount')
        private_key = get_param('jnt_privateKey')

        if not api_account or not private_key:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi',
                    'message': 'Thiếu jnt_apiAccount hoặc jnt_privateKey trong System Parameters!',
                    'type': 'danger',
                }
            }

        client = JTApiUtils(
            api_account=api_account,
            private_key=private_key,
            environment=self.jt_environment
        )
        
        # We don't have a simple 'ping' API, so we try a request with minimal data or just validate credentials logic
        # For now, just show success if parameters exist, or we could try to get something if J&T has a query API.
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thông tin',
                'message': f'Cấu hình System Parameters đã sẵn sàng (Account: {api_account}). Thử tạo đơn để kiểm tra kết nối thực tế.',
                'type': 'success',
            }
        }
