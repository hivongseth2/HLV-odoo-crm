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

    # === Receive config ===
    hlv_barcode_receive_require_detail_scan = fields.Boolean(
        string="Quét chi tiết khi nhận hàng",
        default=False,
        help="Nếu bật, shipper phải quét từng kiện/SP khi nhận. Nếu tắt, chỉ cần quét phiếu.",
    )
    hlv_barcode_receive_skip_package_scan = fields.Boolean(
        string="Bỏ qua quét Kiện khi nhận",
        default=False,
    )
    hlv_barcode_receive_skip_product_scan = fields.Boolean(
        string="Bỏ qua quét SP lẻ khi nhận",
        default=False,
    )

    # === Return config ===
    hlv_barcode_return_require_detail_scan = fields.Boolean(
        string="Quét chi tiết khi trả hàng",
        default=False,
        help="Nếu bật, shipper phải quét từng kiện/SP khi trả. Nếu tắt, chỉ cần chọn phiếu.",
    )
    hlv_barcode_return_skip_package_scan = fields.Boolean(
        string="Bỏ qua quét Kiện khi trả",
        default=False,
    )
    hlv_barcode_return_skip_product_scan = fields.Boolean(
        string="Bỏ qua quét SP lẻ khi trả",
        default=False,
    )
    hlv_barcode_google_maps_api_key = fields.Char(
        string="Google Maps API Key",
        help="API key used by the delivery route planner.",
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

    # === Receive config ===
    hlv_barcode_receive_require_detail_scan = fields.Boolean(
        related="company_id.hlv_barcode_receive_require_detail_scan",
        readonly=False,
    )
    hlv_barcode_receive_skip_package_scan = fields.Boolean(
        related="company_id.hlv_barcode_receive_skip_package_scan",
        readonly=False,
    )
    hlv_barcode_receive_skip_product_scan = fields.Boolean(
        related="company_id.hlv_barcode_receive_skip_product_scan",
        readonly=False,
    )

    # === Return config ===
    hlv_barcode_return_require_detail_scan = fields.Boolean(
        related="company_id.hlv_barcode_return_require_detail_scan",
        readonly=False,
    )
    hlv_barcode_return_skip_package_scan = fields.Boolean(
        related="company_id.hlv_barcode_return_skip_package_scan",
        readonly=False,
    )
    hlv_barcode_return_skip_product_scan = fields.Boolean(
        related="company_id.hlv_barcode_return_skip_product_scan",
        readonly=False,
    )
    hlv_barcode_google_maps_api_key = fields.Char(
        related="company_id.hlv_barcode_google_maps_api_key",
        readonly=False,
    )

