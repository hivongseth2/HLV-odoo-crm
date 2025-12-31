# Copyright 2018-2019 ForgeFlow, S.L.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    purchase_request = fields.Boolean(
        string="Yêu cầu mua hàng",
        help="Chọn ô này để tạo Yêu cầu mua hàng thay vì "
        "tạo Yêu cầu báo giá từ cung ứng.",
        company_dependent=True,
    )
