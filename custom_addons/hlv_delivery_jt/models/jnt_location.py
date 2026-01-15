# -*- coding: utf-8 -*-
from odoo import fields, models

class JntProvince(models.Model):
    _name = "jnt.province"
    _description = "J&T Province"
    _order = "name"
    
    name = fields.Char(string="Tên Tỉnh/Thành", required=True)
    code = fields.Char(string="Mã J&T")

class JntDistrict(models.Model):
    _name = "jnt.district"
    _description = "J&T District"
    _order = "name"
    
    name = fields.Char(string="Tên Quận/Huyện", required=True)
    code = fields.Char(string="Mã J&T")
    province_id = fields.Many2one("jnt.province", string="Tỉnh/Thành", ondelete="cascade")

class JntWard(models.Model):
    _name = "jnt.ward"
    _description = "J&T Ward"
    _order = "name"
    
    name = fields.Char(string="Tên Phường/Xã", required=True)
    jnt_code = fields.Char(string="Mã J&T Ward")
    district_id = fields.Many2one("jnt.district", string="Quận/Huyện", ondelete="cascade")
