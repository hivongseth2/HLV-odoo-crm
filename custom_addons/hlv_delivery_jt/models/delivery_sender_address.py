# -*- coding: utf-8 -*-
from odoo import fields, models, api

class DeliverySenderAddress(models.Model):
    _name = "delivery.sender.address"
    _description = "Cấu hình địa chỉ người gửi"

    name = fields.Char(string="Tên cấu hình", required=True)
    warehouse_id = fields.Many2one("stock.warehouse", string="Kho hàng")
    sender_name = fields.Char(string="Tên người gửi", required=True)
    sender_mobile = fields.Char(string="SĐT người gửi", required=True)
    sender_address = fields.Char(string="Địa chỉ gửi", required=True)
    
    # J&T Locations
    jnt_prov_id = fields.Many2one("jnt.province", string="Tỉnh/Thành gửi (J&T)")
    jnt_city_id = fields.Many2one("jnt.district", string="Quận/Huyện gửi (J&T)",
                                 domain="[('province_id', '=', jnt_prov_id)]")
    jnt_area_id = fields.Many2one("jnt.ward", string="Phường/Xã gửi (J&T)",
                                 domain="[('district_id', '=', jnt_city_id)]")
