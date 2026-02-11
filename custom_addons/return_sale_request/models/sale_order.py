# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    return_sale_request_ids = fields.One2many(
        comodel_name="return.sale.request",
        inverse_name="sale_order_id",
        string="Yêu cầu trả hàng",
    )
    return_sale_request_count = fields.Integer(
        string="Số yêu cầu trả hàng",
        compute="_compute_return_sale_request_count",
    )

    def _compute_return_sale_request_count(self):
        for rec in self:
            rec.return_sale_request_count = len(rec.return_sale_request_ids)

    def action_view_return_sale_requests(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "return_sale_request.action_return_sale_request"
        )
        action["domain"] = [("sale_order_id", "=", self.id)]
        action["context"] = dict(
            self.env.context,
            default_sale_order_id=self.id,
            default_partner_id=self.partner_id.id,
        )
        if self.return_sale_request_count == 1:
            action["view_mode"] = "form"
            action["res_id"] = self.return_sale_request_ids.id
        return action
