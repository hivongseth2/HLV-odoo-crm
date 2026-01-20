# -*- coding: utf-8 -*-
from odoo import fields, models, api
from ..utils.jt_api_utils import JTApiUtils

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    jt_environment = fields.Selection(
        related="company_id.jt_environment",
        readonly=False,
        string="Môi trường J&T",
    )

    # Read-only display fields for credentials from System Parameters
    jt_api_account_display = fields.Char(
        string="J&T apiAccount",
        compute="_compute_jt_credentials",
    )
    jt_private_key_display = fields.Char(
        string="J&T privateKey",
        compute="_compute_jt_credentials",
    )
    jt_customer_code_display = fields.Char(
        string="J&T customerCode",
        compute="_compute_jt_credentials",
    )
    jt_password_display = fields.Char(
        string="J&T password",
        compute="_compute_jt_credentials",
    )

    def _compute_jt_credentials(self):
        get_param = self.env['ir.config_parameter'].sudo().get_param
        for record in self:
            record.jt_api_account_display = get_param('jnt_apiAccount') or 'Chưa cấu hình jnt_apiAccount'
            record.jt_private_key_display = get_param('jnt_privateKey') or 'Chưa cấu hình jnt_privateKey'
            record.jt_customer_code_display = get_param('jnt_customerCode') or 'Chưa cấu hình jnt_customerCode'
            record.jt_password_display = get_param('jnt_password') or 'Chưa cấu hình jnt_password'

    def action_check_jt_connection(self):
        """Test connection to J&T API"""
        get_param = self.env['ir.config_parameter'].sudo().get_param
        api_account = get_param('jnt_apiAccount')
        private_key = get_param('jnt_privateKey')
        customer_code = get_param('jnt_customerCode')
        password = get_param('jnt_password')

        if not api_account or not private_key or not customer_code or not password:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi',
                    'message': 'Thiếu jnt_apiAccount, jnt_privateKey, jnt_customerCode hoặc jnt_password trong System Parameters!',
                    'type': 'danger',
                }
            }

        client = JTApiUtils(
            api_account=api_account,
            private_key=private_key,
            environment=self.jt_environment
        )
        
        # Perform a real connection test using calculate_fee with dummy data
        biz_params = {
            "customerCode": customer_code,
            "password": password.upper(),
            "weight": 0.5,
            "productType": 'EXPRESS',
            "goodsType": 'bm000010',
            "goodsValue": 100000,
            "codMoney": "0",
            "isInsured": 0,
            "sender": {
                "prov": "Hồ Chí Minh",
                "city": "Quận 1",
                "area": "Phường Tân Định"
            },
            "receiver": {
                "prov": "Hà Nội",
                "city": "Quận Hoàn Kiếm",
                "area": "Phường Cửa Đông"
            }
        }
        
        try:
            result = client.calculate_fee(biz_params)
            if result.get('code') == '1':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Thành công',
                        'message': f'Kết nối J&T ({self.jt_environment}) thành công!',
                        'type': 'success',
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Thất bại',
                        'message': f"Lỗi từ J&T: {result.get('msg', 'Unknown Error')}",
                        'type': 'danger',
                        'sticky': True,
                    }
                }
        except Exception as e:
             return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi ngoại lệ',
                    'message': str(e),
                    'type': 'danger',
                }
            }
