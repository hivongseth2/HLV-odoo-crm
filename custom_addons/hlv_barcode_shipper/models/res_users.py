# -*- coding: utf-8 -*-

from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    shipper_name = fields.Char(string="Tên Shipper", help="Tên hiển thị khi shipper quét barcode")
