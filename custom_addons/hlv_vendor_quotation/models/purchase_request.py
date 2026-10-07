# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from ..services.sale_code import sale_code

# YCMH còn sửa được: chưa được thu mua duyệt.
MERGEABLE_STATES = ("draft", "to_approve")


class PurchaseRequest(models.Model):
    _inherit = "purchase.request"

    vendor_quote_ids = fields.One2many("hlv.vendor.quote", "request_id", string="Báo giá NCC")
    hlv_from_quote_page = fields.Boolean(
        string="Lập từ trang Hỏi giá NCC", readonly=True, copy=False,
        help="YCMH lập ở Odoo (không đi từ MISA). Chỉ YCMH loại này được gộp thêm hàng.",
    )
    vendor_quote_count = fields.Integer(
        string="Số báo giá NCC", compute="_compute_vendor_quote_count"
    )

    @api.depends("vendor_quote_ids.state")
    def _compute_vendor_quote_count(self):
        for request in self:
            request.vendor_quote_count = len(
                request.vendor_quote_ids.filtered(lambda q: q.state != "cancel")
            )

    @api.model
    def _mergeable_for_sale_order(self, order):
        """YCMH mới nhất của đơn bán còn gộp được hàng vào: chưa duyệt VÀ lập từ trang hỏi giá.

        Không gộp vào YCMH đi từ MISA: khi còn chờ duyệt, extension đồng bộ lại YCMH đó theo
        từng dòng MISA (misa_line_id) — dòng Odoo chen vào sẽ lệch với MISA.
        Không có → recordset rỗng.
        """
        return self.sudo().search([
            ("sale_order_id", "=", order.id),
            ("state", "in", MERGEABLE_STATES),
            ("hlv_from_quote_page", "=", True),
        ], order="id desc", limit=1).with_env(self.env)

    @api.model
    def _add_sale_order_lines(self, order, line_vals):
        """Đưa hàng của một đơn bán vào YCMH, ngay trên trang hỏi giá NCC.

        Đơn đã có YCMH chưa duyệt (xem _mergeable_for_sale_order) → gộp vào đó theo sản phẩm.
        Không có → tạo YCMH mới; một đơn được có nhiều YCMH (YCMH trước đã duyệt mà mua
        thiếu thì lên YCMH bổ sung).
        YCMH mới dựng giống YCMH đi từ MISA để thu mua xử lý như cũ: "Chờ phê duyệt", giao
        admin, nguồn = số đơn bán, "Người yêu cầu" = mã sale trên đơn (rỗng nếu bản cài
        không có field hoặc đơn chưa có mã).
        line_vals: [{product_id, name, product_qty, product_uom_id}].
        Trả (YCMH, các dòng YCMH vừa thêm/cộng, True nếu là gộp).

        Ghi bằng sudo: sale chỉ có quyền ĐỌC YCMH; việc ghi đi qua đúng đường này.
        """
        if not line_vals:
            raise UserError(_("Chọn ít nhất một mặt hàng của đơn bán."))
        target = self._mergeable_for_sale_order(order)
        if target:
            lines = target.sudo()._merge_lines(line_vals)
            target.sudo().message_post(body=self._lines_message(
                _("Bổ sung hàng từ trang Hỏi giá NCC (đơn %s):", order.name), line_vals
            ))
            return target, lines.with_env(self.env), True

        admin = self.env.ref("base.user_admin", raise_if_not_found=False)
        request = self.sudo().create({
            "requested_by": self.env.uid,
            "assigned_to": admin.id if admin else False,
            "origin": order.name,
            "sale_order_id": order.id,
            "company_id": order.company_id.id,
            "x_misa_requested_by": sale_code(order.sudo()),
            "hlv_from_quote_page": True,
            "line_ids": [Command.create(vals) for vals in line_vals],
        })
        request.button_to_approve()
        request.message_post(body=Markup(_(
            "Tạo từ trang Hỏi giá NCC cho đơn bán <b>%s</b>."
        )) % order.name)
        return request.with_env(self.env), request.line_ids.with_env(self.env), False

    def _merge_lines(self, line_vals):
        """Gộp hàng vào YCMH theo sản phẩm: cùng sản phẩm, cùng nhóm ĐVT (dòng chưa huỷ) thì
        cộng số lượng — quy đổi về ĐVT của dòng đang có; không thì thêm dòng mới.
        Trả các dòng YCMH bị đụng tới."""
        self.ensure_one()
        Line = self.env["purchase.request.line"]
        touched = Line
        for vals in line_vals:
            uom = self.env["uom.uom"].browse(vals["product_uom_id"])
            line = self.line_ids.filtered(
                lambda l: l.product_id.id == vals["product_id"]
                and not l.cancelled
                and l.product_uom_id.category_id == uom.category_id
            )[:1]
            if line:
                line.product_qty += uom._compute_quantity(vals["product_qty"], line.product_uom_id)
            else:
                line = Line.create(dict(vals, request_id=self.id))
            touched |= line
        return touched

    @api.model
    def _lines_message(self, title, line_vals):
        items = Markup("").join(
            Markup("<li>%s: +%s</li>") % (vals["name"], vals["product_qty"]) for vals in line_vals
        )
        return Markup("<p>%s</p><ul>%s</ul>") % (title, items)

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
