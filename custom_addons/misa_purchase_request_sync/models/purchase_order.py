# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    purchase_request_id = fields.Many2one(
        comodel_name="purchase.request",
        string="YCMH gốc",
        compute="_compute_purchase_request_id",
        store=True,
        help="Yêu cầu mua hàng gốc đã tạo ra đơn mua hàng này.",
    )

    @api.depends("order_line.purchase_request_lines.request_id")
    def _compute_purchase_request_id(self):
        for po in self:
            prs = po.order_line.mapped("purchase_request_lines.request_id")
            po.purchase_request_id = prs[:1] if prs else False