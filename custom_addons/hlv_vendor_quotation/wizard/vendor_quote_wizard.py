# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

DEFAULT_DEADLINE_DAYS = 2


class VendorQuoteWizard(models.TransientModel):
    """Gửi cùng danh sách mặt hàng cho nhiều NCC một lần, có gợi ý NCC từ lịch sử mua.

    Hai cửa vào:
    - từ YCMH (request_id): mặt hàng lấy từ dòng YCMH, mỗi NCC một báo giá mới;
    - từ một báo giá nháp sale đã nhập hàng (source_quote_id): NCC đầu tiên nhận chính báo
      giá đó, mỗi NCC còn lại nhận một bản sao.
    """

    _name = "hlv.vendor.quote.wizard"
    _description = "Hỏi giá nhiều nhà cung cấp"

    request_id = fields.Many2one("purchase.request", string="Yêu cầu mua hàng")
    source_quote_id = fields.Many2one("hlv.vendor.quote", string="Báo giá nháp")
    partner_ids = fields.Many2many("res.partner", string="Nhà cung cấp khác")
    suggestion_ids = fields.One2many(
        "hlv.vendor.quote.wizard.suggestion", "wizard_id", string="NCC gợi ý"
    )
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
        Quote = self.env["hlv.vendor.quote"]
        source = Quote.browse(res.get("source_quote_id"))
        request = self.env["purchase.request"].browse(res.get("request_id"))
        if source:
            products = source.line_ids.product_id
            res.update(
                request_id=source.request_id.id,
                date_deadline=source.date_deadline or res.get("date_deadline"),
                note=source.note or res.get("note"),
            )
        else:
            lines = Quote._quotable_request_lines(request) if request else self.env["purchase.request.line"]
            products = lines.product_id
            if "request_line_ids" in fields_list:
                res["request_line_ids"] = [Command.set(lines.ids)]
        if "suggestion_ids" in fields_list:
            res["suggestion_ids"] = self._suggestion_commands(products, self._quoted_vendors(request, source))
        return res

    @api.onchange("request_line_ids")
    def _onchange_request_line_ids(self):
        """Đổi mặt hàng thì gợi ý lại; giữ tích của NCC vẫn còn trong danh sách mới."""
        if self.source_quote_id:
            return
        kept = self.suggestion_ids.filtered("selected").partner_id
        self.suggestion_ids = self._suggestion_commands(
            self.request_line_ids.product_id, self._quoted_vendors(self.request_id), kept
        )

    @api.model
    def _quoted_vendors(self, request, source=None):
        """NCC đã có báo giá mở cho YCMH này (và NCC của báo giá nguồn) — không gợi ý lại."""
        vendors = self.env["hlv.vendor.quote"]._vendors_with_open_quote(request)
        if source:
            vendors |= source.access_id.partner_id
        return vendors

    @api.model
    def _suggestion_commands(self, products, exclude, selected_partners=None):
        suggestions = self.env["hlv.vendor.suggestion"].suggest(products, exclude)
        total = len(products)
        selected_ids = set((selected_partners or self.env["res.partner"]).ids)
        commands = [Command.clear()]
        for item in suggestions:
            matched = products.filtered(lambda p, ids=item["product_ids"]: p.id in ids)
            commands.append(Command.create({
                "partner_id": item["partner_id"],
                "matched_label": f"{len(item['product_ids'])}/{total}",
                "matched_products": ", ".join(matched.mapped("display_name")),
                "order_count": item["order_count"],
                "last_date": item["last_date"],
                "from_pricelist": item["from_pricelist"],
                "selected": item["partner_id"] in selected_ids,
            }))
        return commands

    def _chosen_vendors(self):
        return (
            self.partner_ids.commercial_partner_id
            | self.suggestion_ids.filtered("selected").partner_id
        )

    def action_create_quotes(self):
        self.ensure_one()
        vendors = self._chosen_vendors() - self._quoted_vendors(self.request_id, self.source_quote_id)
        if self.source_quote_id:
            quotes = self._send_source_quote(vendors)
        else:
            quotes = self._create_request_quotes(vendors)

        action = self.env["ir.actions.act_window"]._for_xml_id(
            "hlv_vendor_quotation.action_vendor_quote"
        )
        action.update({
            "name": _("Gửi link cho NCC"),
            "domain": [("id", "in", quotes.ids)],
            "context": {},
            "views": [(self.env.ref("hlv_vendor_quotation.view_vendor_quote_share_list").id, "list"),
                      (False, "form")],
        })
        return action

    def _create_request_quotes(self, vendors):
        Quote = self.env["hlv.vendor.quote"]
        line_vals = Quote._line_vals_from_request_lines(
            self.request_line_ids.sorted(lambda l: (l.sequence, l.id))
        )
        return Quote._create_and_send(
            vendors, line_vals, self.request_id, self.date_deadline, self.note
        )

    def _send_source_quote(self, vendors):
        source = self.source_quote_id
        if source.state != "draft":
            raise UserError(_("Chỉ gửi được từ báo giá đang ở trạng thái nháp."))
        if not vendors and not source.partner_id:
            raise UserError(_("Tích ít nhất một nhà cung cấp gợi ý, hoặc chọn thêm NCC khác."))
        common = {"date_deadline": self.date_deadline, "note": self.note}
        if not source.partner_id:
            source.write({**common, "partner_id": vendors[0].id})
            vendors = vendors[1:]
        else:
            source.write(common)
        quotes = source
        for vendor in vendors:
            quotes |= source.copy({**common, "partner_id": vendor.id})
        quotes.action_send()
        return quotes


class VendorQuoteWizardSuggestion(models.TransientModel):
    _name = "hlv.vendor.quote.wizard.suggestion"
    _description = "NCC gợi ý trong wizard hỏi giá"
    _order = "id"

    wizard_id = fields.Many2one("hlv.vendor.quote.wizard", required=True, ondelete="cascade")
    selected = fields.Boolean(string="Hỏi giá")
    # Readonly đặt ở view kèm force_save: field readonly ở Python không được web client gửi
    # lại khi lưu wizard, dòng gợi ý sẽ mất NCC.
    partner_id = fields.Many2one("res.partner", string="Nhà cung cấp", required=True)
    matched_label = fields.Char(string="Mặt hàng từng mua")
    matched_products = fields.Char(string="Gồm")
    order_count = fields.Integer(string="Số đơn đã mua")
    last_date = fields.Date(string="Lần mua gần nhất")
    from_pricelist = fields.Boolean(string="Có trong bảng giá NCC")
