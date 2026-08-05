# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_return_requested = fields.Boolean(
        string="Khách đề nghị đổi/trả",
        default=False,
        tracking=True,
        help="Khách hàng Zalo Mini App đã gửi yêu cầu đổi/trả hàng",
    )