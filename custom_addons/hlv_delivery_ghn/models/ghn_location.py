# -*- coding: utf-8 -*-
from odoo import fields, models, api

class GHNProvince(models.Model):
    _name = "ghn.province"
    _description = "GHN Province"
    
    province_id = fields.Integer(string="GHN Province ID", required=True)
    name = fields.Char(string="Province Name", required=True)

class GHNDistrict(models.Model):
    _name = "ghn.district"
    _description = "GHN District"
    
    district_id = fields.Integer(string="GHN District ID", required=True)
    name = fields.Char(string="District Name", required=True)
    province_id = fields.Many2one("ghn.province", string="Province", ondelete="cascade")

class GHNWard(models.Model):
    _name = "ghn.ward"
    _description = "GHN Ward"
    
    ward_code = fields.Char(string="GHN Ward Code", required=True)
    name = fields.Char(string="Ward Name", required=True)
    district_id = fields.Many2one("ghn.district", string="District", ondelete="cascade")
