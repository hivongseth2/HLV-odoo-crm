# -*- coding: utf-8 -*-
from odoo import fields, models

class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    ghn_province_id = fields.Many2one("ghn.province", string="Tỉnh/Thành gửi (GHN)")
    ghn_district_id = fields.Many2one("ghn.district", string="Quận/Huyện gửi (GHN)",
                                     domain="[('province_id', '=', ghn_province_id)]")
    ghn_ward_id = fields.Many2one("ghn.ward", string="Phường/Xã gửi (GHN)",
                                   domain="[('district_id', '=', ghn_district_id)]")
    
    ghn_shop_id = fields.Char(string="Mã Shop ID (GHN)")
    ghn_shop_id_heavy = fields.Char(string="Mã Shop ID hàng nặng (GHN)")
