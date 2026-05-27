# -*- coding: utf-8 -*-
from odoo import fields, models


class ShopeeResultViewer(models.TransientModel):
    _name = 'shopee.result.viewer'
    _description = 'Kết quả Shopee API'

    title = fields.Char(string='Tiêu đề', readonly=True)
    result_json = fields.Text(string='Kết quả', readonly=True)
