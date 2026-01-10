# -*- coding: utf-8 -*-

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    hlv_barcode_skip_package_scan = fields.Boolean(
        string="Bỏ qua quét Kiện (Package)",
        default=False,
        help="Nếu bật, các kiện (Package) sẽ tự động được coi là đã quét, không cần quét.",
    )
    hlv_barcode_skip_product_scan = fields.Boolean(
        string="Bỏ qua quét Sản phẩm lẻ",
        default=False,
        help="Nếu bật, các sản phẩm lẻ sẽ tự động được coi là đã quét, không cần quét.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_barcode_skip_package_scan = fields.Boolean(
        related="company_id.hlv_barcode_skip_package_scan",
        readonly=False,
    )
    hlv_barcode_skip_product_scan = fields.Boolean(
        related="company_id.hlv_barcode_skip_product_scan",
        readonly=False,
    )


