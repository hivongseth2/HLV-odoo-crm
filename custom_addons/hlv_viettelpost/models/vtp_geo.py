from odoo import models, fields

class VTPProvince(models.Model):
    _name = "vtp.province"
    _description = "VTP Province"
    _order = "name"
    name = fields.Char(required=True)
    vtp_id = fields.Integer(required=True, index=True)

class VTPDistrict(models.Model):
    _name = "vtp.district"
    _description = "VTP District"
    _order = "name"
    name = fields.Char(required=True)
    vtp_id = fields.Integer(required=True, index=True)
    province_id = fields.Many2one("vtp.province", required=True, ondelete="cascade")

class VTPWard(models.Model):
    _name = "vtp.ward"
    _description = "VTP Ward"
    _order = "name"
    name = fields.Char(required=True)
    vtp_id = fields.Integer(required=True, index=True)
    district_id = fields.Many2one("vtp.district", required=True, ondelete="cascade")
