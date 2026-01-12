# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError
from ..utils.ghn_api_utils import GHNApiUtils

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ghn_api_token = fields.Char(
        related="company_id.ghn_api_token",
        readonly=False,
        string="GHN API Token",
    )
    ghn_shop_id = fields.Integer(
        related="company_id.ghn_shop_id",
        readonly=False,
        string="GHN Shop ID",
    )
    ghn_environment = fields.Selection(
        related="company_id.ghn_environment",
        readonly=False,
        string="GHN Environment",
    )

    def action_check_ghn_connection(self):
        client = GHNApiUtils(
            token=self.ghn_api_token,
            shop_id=self.ghn_shop_id,
            environment=self.ghn_environment
        )
        try:
            # get_provinces only checks Token
            provinces = client.get_provinces()
            if not provinces:
                raise UserError("Token không hợp lệ hoặc không thể lấy dữ liệu tỉnh thành.")
            
            # get_services checks both Token and ShopId
            # We use 1442 (HCMC) and 1442 as dummy districts to test
            services = client.get_services(1442, 1442)
            if services is not None: # get_services returns empty list if success but no services, or None/Error if fail
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Thành công',
                        'message': 'Kết nối GHN (Token & Shop ID) thành công!',
                        'sticky': False,
                        'type': 'success',
                    }
                }
            else:
                raise UserError("Kết nối tới Shop ID thất bại. Vui lòng kiểm tra lại Shop ID.")
        except Exception as e:
            raise UserError(f"Lỗi kết nối: {str(e)}")

    def action_sync_ghn_locations(self):
        client = GHNApiUtils(
            token=self.ghn_api_token,
            shop_id=self.ghn_shop_id,
            environment=self.ghn_environment
        )
        
        # Sync Provinces
        provinces = client.get_provinces()
        if not provinces:
            return True

        ProvinceModel = self.env['ghn.province']
        DistrictModel = self.env['ghn.district']
        
        for p in provinces:
            exist_p = ProvinceModel.search([('province_id', '=', p['ProvinceID'])], limit=1)
            if not exist_p:
                exist_p = ProvinceModel.create({
                    'province_id': p['ProvinceID'],
                    'name': p['ProvinceName']
                })
            
            # Sync Districts for this province
            districts = client.get_districts(p['ProvinceID'])
            if districts:
                for d in districts:
                    exist_d = DistrictModel.search([('district_id', '=', d['DistrictID'])], limit=1)
                    if not exist_d:
                        DistrictModel.create({
                            'district_id': d['DistrictID'],
                            'name': d['DistrictName'],
                            'province_id': exist_p.id
                        })
        
        return True
