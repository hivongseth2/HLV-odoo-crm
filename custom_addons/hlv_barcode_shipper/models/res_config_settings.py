# -*- coding: utf-8 -*-

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    # hlv_barcode_shipper_allow_package = fields.Boolean(
    #     string="Cho phép quét kiện (Package)",
    #     default=True,
    #     help="Nếu tắt, Shipper sẽ phải quét từng sản phẩm lẻ bên trong kiện, không được quét mã kiện.",
    # )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # hlv_barcode_shipper_allow_package = fields.Boolean(
    #     related="company_id.hlv_barcode_shipper_allow_package",
    #     readonly=False,
    # )
