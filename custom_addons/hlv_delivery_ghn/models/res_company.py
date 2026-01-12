# -*- coding: utf-8 -*-
from odoo import fields, models

class ResCompany(models.Model):
    _inherit = "res.company"

    ghn_api_token = fields.Char(string="Mã Token API GHN")
    ghn_shop_id = fields.Char(string="Mã Cửa hàng (Shop ID)")
    ghn_shop_id_heavy = fields.Char(string="Mã Cửa hàng hàng nặng (>10kg)")
    ghn_default_warehouse_id = fields.Many2one('stock.warehouse', string="Kho hàng mặc định cho WooCommerce")
    ghn_wp_api_token = fields.Char(string="Mã Token bảo mật API WordPress", help="Dùng để xác thực yêu cầu từ WordPress")
    ghn_environment = fields.Selection([
        ('test', 'Môi trường Thử nghiệm (Sandbox)'),
        ('prod', 'Môi trường Thực tế (Production)')
    ], string="Môi trường GHN", default='test')
