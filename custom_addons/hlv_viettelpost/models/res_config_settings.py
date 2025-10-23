from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    vtp_api_base = fields.Char(string="VTP API Base", default="https://partnerdev.viettelpost.vn/v2")
    vtp_username = fields.Char(string="VTP Username")
    vtp_password = fields.Char(string="VTP Password")
    vtp_token = fields.Char(string="VTP Token", readonly=True)

    vtp_shop_province_code = fields.Char("Shop Province Code")
    vtp_shop_district_code = fields.Char("Shop District Code")
    vtp_shop_ward_code = fields.Char("Shop Ward Code")
    vtp_shop_address = fields.Char("Shop Address")
    vtp_shop_phone = fields.Char("Shop Phone")

    def set_values(self):
        res = super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('vtp.api_base', self.vtp_api_base or '')
        ICP.set_param('vtp.username', self.vtp_username or '')
        ICP.set_param('vtp.password', self.vtp_password or '')
        ICP.set_param('vtp.shop_province_code', self.vtp_shop_province_code or '')
        ICP.set_param('vtp.shop_district_code', self.vtp_shop_district_code or '')
        ICP.set_param('vtp.shop_ward_code', self.vtp_shop_ward_code or '')
        ICP.set_param('vtp.shop_address', self.vtp_shop_address or '')
        ICP.set_param('vtp.shop_phone', self.vtp_shop_phone or '')
        return res

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        res.update(
            vtp_api_base = ICP.get_param('vtp.api_base', 'https://partnerdev.viettelpost.vn/v2'),
            vtp_username = ICP.get_param('vtp.username', ''),
            vtp_password = ICP.get_param('vtp.password', ''),
            vtp_token = ICP.get_param('vtp.token', ''),
            vtp_shop_province_code = ICP.get_param('vtp.shop_province_code', ''),
            vtp_shop_district_code = ICP.get_param('vtp.shop_district_code', ''),
            vtp_shop_ward_code = ICP.get_param('vtp.shop_ward_code', ''),
            vtp_shop_address = ICP.get_param('vtp.shop_address', ''),
            vtp_shop_phone = ICP.get_param('vtp.shop_phone', ''),
        )
        return res

    def action_vtp_login(self):
        self.env['vtp.api'].vtp_login(self.vtp_username, self.vtp_password)
        self.vtp_token = self.env['ir.config_parameter'].sudo().get_param('vtp.token')
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'title': 'VTP', 'message': 'Đăng nhập thành công', 'type': 'success'}}
