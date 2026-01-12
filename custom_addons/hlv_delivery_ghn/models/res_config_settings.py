# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError
from ..utils.ghn_api_utils import GHNApiUtils
import logging

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ghn_api_token = fields.Char(
        related="company_id.ghn_api_token",
        readonly=False,
        string="Mã Token API GHN",
    )
    ghn_shop_id = fields.Char(
        related="company_id.ghn_shop_id",
        readonly=False,
        string="Mã Cửa hàng (Shop ID)",
    )
    ghn_shop_id_heavy = fields.Char(
        related="company_id.ghn_shop_id_heavy",
        readonly=False,
        string="Mã Cửa hàng hàng nặng (>10kg)",
    )
    ghn_default_warehouse_id = fields.Many2one(
        'stock.warehouse',
        related="company_id.ghn_default_warehouse_id",
        readonly=False,
        string="Kho hàng mặc định cho WooCommerce",
    )
    ghn_wp_api_token = fields.Char(
        related="company_id.ghn_wp_api_token",
        readonly=False,
        string="Mã Token bảo mật API WordPress",
    )
    ghn_environment = fields.Selection(
        related="company_id.ghn_environment",
        readonly=False,
        string="Môi trường GHN",
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
            # We use 1442 (HCMC) as dummy districts to test
            result = client.get_services(1442, 1442)
            if result.get('success'):
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
                raise UserError(f"Kết nối Shop ID thất bại: {result.get('error')}")
        except Exception as e:
            raise UserError(f"Lỗi kết nối: {str(e)}")

    def action_get_available_shops(self):
        client = GHNApiUtils(
            token=self.ghn_api_token,
            shop_id=None,
            environment=self.ghn_environment
        )
        result = client.get_shops()
        if result.get('success'):
            shops = result.get('data', {}).get('shops', [])
            if not shops:
                raise UserError("Không tìm thấy Shop nào liên kết với Token này.")
            
            shop_info = "\n".join([f"- Name: {s['name']} | ID: {s['_id']}" for s in shops])
            raise UserError(f"Danh sách Shop ID khả dụng:\n{shop_info}")
        else:
            raise UserError(f"Lỗi khi lấy danh sách shop: {result.get('error')}")

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
        
        _logger.info("GHN Sync: Found %s provinces", len(provinces))
        for p in provinces:
            exist_p = ProvinceModel.search([('province_id', '=', p['ProvinceID'])], limit=1)
            if exist_p:
                exist_p.write({'name': p['ProvinceName']})
            else:
                exist_p = ProvinceModel.create({
                    'province_id': p['ProvinceID'],
                    'name': p['ProvinceName']
                })
            
            # Sync Districts for this province
            districts = client.get_districts(p['ProvinceID'])
            if districts:
                _logger.info("GHN Sync: Found %s districts for province %s", len(districts), p['ProvinceName'])
                for d in districts:
                    exist_d = DistrictModel.search([('district_id', '=', d['DistrictID'])], limit=1)
                    if exist_d:
                        exist_d.write({
                            'name': d['DistrictName'],
                            'province_id': exist_p.id
                        })
                    else:
                        DistrictModel.create({
                            'district_id': d['DistrictID'],
                            'name': d['DistrictName'],
                            'province_id': exist_p.id
                        })
        
        _logger.info("GHN Sync Completed!")
        return True

    def action_wipe_and_sync_ghn_locations(self):
        """Wipe all existing records and perform a fresh sync."""
        self.env['ghn.ward'].sudo().search([]).unlink()
        self.env['ghn.district'].sudo().search([]).unlink()
        self.env['ghn.province'].sudo().search([]).unlink()
        return self.action_sync_ghn_locations()
