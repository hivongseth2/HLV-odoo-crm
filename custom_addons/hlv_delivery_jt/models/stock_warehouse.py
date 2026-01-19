# -*- coding: utf-8 -*-
from odoo import fields, models

class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    jnt_prov_id = fields.Many2one("jnt.province", string="Tỉnh/Thành gửi (J&T)")
    jnt_city_id = fields.Many2one("jnt.district", string="Quận/Huyện gửi (J&T)",
                                 domain="[('province_id', '=', jnt_prov_id)]")
    jnt_area_id = fields.Many2one("jnt.ward", string="Phường/Xã gửi (J&T)",
                                 domain="[('district_id', '=', jnt_city_id)]")
    
    sender_address_ids = fields.One2many("delivery.sender.address", "warehouse_id", string="Hồ sơ người gửi")
