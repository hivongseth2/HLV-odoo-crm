# -*- coding: utf-8 -*-
from odoo import fields, models, api
from ..utils.ghn_api_utils import GHNApiUtils

class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    ghn_province_id = fields.Many2one("ghn.province", string="Tỉnh/Thành gửi (GHN)")
    ghn_district_id = fields.Many2one("ghn.district", string="Quận/Huyện gửi (GHN)",
                                     domain="[('province_id', '=', ghn_province_id)]")
    ghn_ward_id = fields.Many2one("ghn.ward", string="Phường/Xã gửi (GHN)",
                                   domain="[('district_id', '=', ghn_district_id)]")
    
    ghn_shop_id = fields.Char(string="Mã Shop ID (GHN)")
    ghn_shop_id_heavy = fields.Char(string="Mã Shop ID hàng nặng (GHN)")

    @api.onchange('ghn_district_id')
    def _onchange_ghn_district_id(self):
        """Fetch wards from GHN when district changes in warehouse config."""
        if not self.ghn_district_id:
            return
        
        company = self.env.company
        client = GHNApiUtils(
            token=company.ghn_api_token,
            shop_id=company.ghn_shop_id,
            environment=company.ghn_environment
        )
        
        wards = client.get_wards(self.ghn_district_id.district_id)
        WardModel = self.env['ghn.ward']
        for w in wards:
            exist = WardModel.search([
                ('ward_code', '=', w['WardCode']),
                ('district_id', '=', self.ghn_district_id.id)
            ], limit=1)
            if not exist:
                WardModel.create({
                    'ward_code': w['WardCode'],
                    'name': w['WardName'],
                    'district_id': self.ghn_district_id.id
                })
