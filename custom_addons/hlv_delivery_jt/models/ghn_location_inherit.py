# -*- coding: utf-8 -*-
from odoo import fields, models

class GHNProvince(models.Model):
    _inherit = "ghn.province"
    
    jnt_code = fields.Char(string="Mã J&T Province")

class GHNDistrict(models.Model):
    _inherit = "ghn.district"
    
    jnt_code = fields.Char(string="Mã J&T District")

class GHNWard(models.Model):
    _inherit = "ghn.ward"
    
    jnt_code = fields.Char(string="Mã J&T Ward")
