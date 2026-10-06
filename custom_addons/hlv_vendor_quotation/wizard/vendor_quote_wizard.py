# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

DEFAULT_DEADLINE_DAYS = 2


class VendorQuoteWizard(models.TransientModel):
    """Từ một YCMH, gửi cùng danh sách mặt hàng cho nhiều NCC một lần."""

    _name = "hlv.vendor.quote.wizard"
    _description = "Hỏi giá nhiều nhà cung cấp"

    request_id = fields.Many2one("purchase.request", string="Yêu cầu mua hàng", required=True)
    partner_ids = fields.Many2many("res.partner", string="Nhà cung cấp", required=True)
    request_line_ids = fields.Many2many(
        "purchase.request.line",
        string="Mặt hàng cần báo giá",
        domain="[('request_id', '=', request_id)]",
    )
    date_deadline = fields.Date(
        string="Hạn báo giá",
        default=lambda self: fields.Date.context_today(self) + timedelta(days=DEFAULT_DEADLINE_DAYS),
    )
    note = fields.Text(string="Lời nhắn gửi NCC")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        request = self.env["purchase.request"].browse(res.get("request_id"))
        if request and "request_line_ids" in fields_list:
            lines = self.env["hlv.vendor.quote"]._quotable_request_lines(request)
            res["request_line_ids"] = [Command.set(lines.ids)]
        return res

    def action_create_quotes(self):
        self.ensure_one()
        if not self.request_line_ids:
            raise UserError(_("Chọn ít nhất một mặt hàng cần báo giá."))

        Quote = self.env["hlv.vendor.quote"]
        quoted_vendors = self.request_id.vendor_quote_ids.filtered(
            lambda q: q.state != "cancel"
        ).access_id.partner_id
        vendors = self.partner_ids.commercial_partner_id - quoted_vendors
        if not vendors:
            raise UserError(_(
                "Các NCC đã chọn đều đã có yêu cầu báo giá cho %s.", self.request_id.name
            ))

        line_vals = Quote._line_vals_from_request_lines(
            self.request_line_ids.sorted(lambda l: (l.sequence, l.id))
        )
        quotes = Quote.create([
            {
                "request_id": self.request_id.id,
                "partner_id": vendor.id,
                "date_deadline": self.date_deadline,
                "note": self.note,
                "state": "sent",
                "line_ids": [Command.create(vals) for vals in line_vals],
            }
            for vendor in vendors
        ])

        action = self.env["ir.actions.act_window"]._for_xml_id(
            "hlv_vendor_quotation.action_vendor_quote"
        )
        action.update({
            "name": _("Gửi link cho NCC"),
            "domain": [("id", "in", quotes.ids)],
            "views": [(self.env.ref("hlv_vendor_quotation.view_vendor_quote_share_list").id, "list"),
                      (False, "form")],
        })
        return action
