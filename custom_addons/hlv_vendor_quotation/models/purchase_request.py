# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PurchaseRequest(models.Model):
    _inherit = "purchase.request"

    vendor_quote_ids = fields.One2many("hlv.vendor.quote", "request_id", string="Báo giá NCC")
    vendor_quote_count = fields.Integer(
        string="Số báo giá NCC", compute="_compute_vendor_quote_count"
    )

    @api.depends("vendor_quote_ids.state")
    def _compute_vendor_quote_count(self):
        for request in self:
            request.vendor_quote_count = len(
                request.vendor_quote_ids.filtered(lambda q: q.state != "cancel")
            )

    def action_open_vendor_quote_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Hỏi giá nhà cung cấp",
            "res_model": "hlv.vendor.quote.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id},
        }

    def action_view_vendor_quotes(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "hlv_vendor_quotation.action_vendor_quote"
        )
        action["domain"] = [("request_id", "=", self.id)]
        action["context"] = {"default_request_id": self.id}
        return action

    def action_compare_vendor_quotes(self):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "hlv_vendor_quotation.action_vendor_quote_compare"
        )
        action["domain"] = [
            ("request_id", "in", self.ids),
            ("quote_state", "in", ("quoted", "done")),
        ]
        return action
