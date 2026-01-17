# -*- coding: utf-8 -*-
from odoo import fields, models, api

class GHNProvince(models.Model):
    _name = "ghn.province"
    _description = "GHN Province"
    
    province_id = fields.Integer(string="Mã Tỉnh/Thành", required=True)
    name = fields.Char(string="Tên Tỉnh/Thành", required=True)

class GHNDistrict(models.Model):
    _name = "ghn.district"
    _description = "GHN District"
    
    district_id = fields.Integer(string="Mã Quận/Huyện", required=True)
    name = fields.Char(string="Tên Quận/Huyện", required=True)
    province_id = fields.Many2one("ghn.province", string="Tỉnh/Thành", ondelete="cascade")

class GHNWard(models.Model):
    _name = "ghn.ward"
    _description = "GHN Ward"
    
    ward_code = fields.Char(string="Mã Phường/Xã", required=True)
    name = fields.Char(string="Tên Phường/Xã", required=True)
    district_id = fields.Many2one("ghn.district", string="Quận/Huyện", ondelete="cascade")
