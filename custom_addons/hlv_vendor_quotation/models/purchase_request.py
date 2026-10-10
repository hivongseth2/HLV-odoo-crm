# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from ..services.sale_code import sale_code

# YCMH còn sửa được: chưa được thu mua duyệt.
MERGEABLE_STATES = ("draft", "to_approve")
# Trường lựa chọn NCC / giá trên dòng YCMH (thu mua: actual_*; sale đề xuất: sale_proposed_*, misa_*)
# — gộp hàng vào dòng có sẵn thì lấy theo lần chọn mới nhất.
CHOICE_FIELD_PREFIXES = ("actual_", "sale_proposed_", "misa_")
# Phiếu hỏi giá còn chọn được NCC — chỉ những phiếu này được nhả lựa chọn khi YCMH bị từ chối.
INQUIRY_ACTIVE_STATES = ("open", "requested")


class PurchaseRequest(models.Model):
    _inherit = "purchase.request"

    vendor_quote_ids = fields.One2many("hlv.vendor.quote", "request_id", string="Báo giá NCC")
    hlv_from_quote_page = fields.Boolean(
        string="Lập từ trang Hỏi giá NCC", readonly=True, copy=False,
        help="YCMH lập ở Odoo (không đi từ MISA). Chỉ YCMH loại này được gộp thêm hàng.",
    )
    hlv_inquiry_ids = fields.Many2many(
        "hlv.vendor.inquiry", string="Phiếu hỏi giá", compute="_compute_hlv_inquiry_ids"
    )
    hlv_inquiry_count = fields.Integer(string="Số phiếu hỏi giá", compute="_compute_hlv_inquiry_count")
    vendor_quote_count = fields.Integer(
        string="Số báo giá NCC", compute="_compute_vendor_quote_count"
    )

    def write(self, vals):
        rejecting = self.filtered(lambda r: r.state != "rejected") if vals.get("state") == "rejected" else self.browse()
        result = super().write(vals)
        if rejecting:
            rejecting._hlv_release_rejected_choices()
        return result

    def _hlv_release_rejected_choices(self):
        """YCMH bị thu mua từ chối: bỏ chọn các NCC đã lên YCMH này (phiếu hỏi giá).

        Giữ lựa chọn thì mặt hàng vẫn như "đã chốt NCC" dù chẳng ai được mua, và sale không bỏ chọn
        được. Dòng báo giá vẫn trỏ dòng YCMH cũ để sale thấy YCMH nào bị từ chối; chọn lại NCC rồi lên
        YCMH mới (hlv.vendor.quote.line._hlv_needs_request).
        """
        chosen = self.env["hlv.vendor.quote.line"].sudo().search([
            ("selected", "=", True),
            ("inquiry_line_id.inquiry_id.state", "in", INQUIRY_ACTIVE_STATES),
            "|", ("request_line_id.request_id", "in", self.ids), ("backorder_request_line_id.request_id", "in", self.ids),
        ])
        if not chosen:
            return
        chosen.write({"selected": False, "chosen_qty": 0.0})
        for inquiry in chosen.inquiry_line_id.inquiry_id:
            lines = chosen.filtered(lambda l, i=inquiry: l.inquiry_line_id.inquiry_id == i)
            requests = lines._hlv_own_request_lines().request_id & self
            inquiry.message_post(body=Markup(_(
                "YCMH <b>%s</b> bị thu mua từ chối — đã bỏ chọn NCC cho %s sản phẩm. Chọn lại NCC rồi lên YCMH mới."
            )) % (", ".join(requests.mapped("name")), len(lines.inquiry_line_id)))

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
    def _add_request_lines(self, line_vals, order=None, source="", requester_code="", merge_into=None):
        """Đưa hàng vào YCMH lập ở Odoo (YCMH không còn lập trên MISA).

        merge_into (YCMH gần nhất của phiếu hỏi giá) còn chưa duyệt → gộp vào đó. Không thì có
        đơn bán và đơn đã có YCMH chưa duyệt (xem _mergeable_for_sale_order) → gộp vào đó
        theo sản phẩm. Không thì tạo YCMH mới — một đơn được có nhiều YCMH (YCMH trước đã
        duyệt mà mua thiếu thì lên YCMH bổ sung).
        YCMH mới dựng giống YCMH đi từ MISA để thu mua xử lý như cũ: "Chờ phê duyệt", giao
        admin, "Người yêu cầu" = mã sale (requester_code, không có thì lấy mã trên đơn bán; rỗng
        nếu đều thiếu). Tài liệu gốc CHỈ là số đơn bán, không có thì để trống — đơn mua lấy
        origin từ đây, mà origin là mã đơn hàng của khách để thu mua / MISA khớp đơn; hỏi giá
        khi khách chưa chốt thì sale điền sau (purchase.order._hlv_set_origin). source: tên
        phiếu hỏi giá, chỉ để ghi chatter.
        line_vals: [{product_id, name, product_qty, product_uom_id, actual_*...}].
        Trả (YCMH, list dòng YCMH ứng với từng phần tử line_vals theo thứ tự, True nếu là gộp).

        Ghi bằng sudo: sale chỉ có quyền ĐỌC YCMH; việc ghi đi qua đúng đường này.
        """
        if not line_vals:
            raise UserError(_("Chọn ít nhất một mặt hàng."))
        target = self.browse()
        if merge_into and merge_into.sudo().state in MERGEABLE_STATES and merge_into.sudo().hlv_from_quote_page:
            target = merge_into
        elif order:
            target = self._mergeable_for_sale_order(order)
        if target:
            lines = target.sudo()._merge_lines(line_vals)
            target.sudo().message_post(body=self._lines_message(
                _("Bổ sung hàng từ trang Hỏi giá NCC (%s):", source or order.name), line_vals
            ))
            return target, [line.with_env(self.env) for line in lines], True

        admin = self.env.ref("base.user_admin", raise_if_not_found=False)
        request = self.sudo().create({
            "requested_by": self.env.uid,
            "assigned_to": admin.id if admin else False,
            "origin": order.name if order else False,
            "sale_order_id": order.id if order else False,
            "company_id": (order.company_id if order else self.env.company).id,
            "x_misa_requested_by": requester_code or (sale_code(order.sudo()) if order else ""),
            "hlv_from_quote_page": True,
            "line_ids": [Command.create(vals) for vals in line_vals],
        })
        request.button_to_approve()
        request.message_post(body=Markup(_("Tạo từ trang Hỏi giá NCC (%s).")) % (source or order.name))
        # Dòng tạo theo đúng thứ tự line_vals nên id tăng dần; sắp theo id thay vì tin _order
        # của purchase.request.line (OCA để "id desc", module MISA đổi thành "id").
        lines = request.line_ids.sorted("id")
        return request.with_env(self.env), [line.with_env(self.env) for line in lines], False

    def _merge_lines(self, line_vals):
        """Gộp hàng vào YCMH theo (sản phẩm, NCC): cùng sản phẩm, cùng NCC (actual_supplier_id), cùng
        nhóm ĐVT, cùng loại phần (giao ngay / NCC hẹn — phần hẹn còn phải cùng ngày cần), dòng chưa huỷ
        thì cộng số lượng — quy đổi về ĐVT của dòng đang có — và ghi đè NCC/giá đã chọn
        (CHOICE_FIELD_PREFIXES) bằng lựa chọn mới nhất; không thì thêm dòng mới. Một sản phẩm mua của
        nhiều NCC nên mỗi NCC một dòng — wizard Tạo RFQ ra mỗi NCC một đơn.
        Trả list dòng YCMH ứng với từng phần tử line_vals (có thể lặp nếu hai phần tử cùng
        gộp vào một dòng)."""
        self.ensure_one()
        Line = self.env["purchase.request.line"]
        result = []
        for vals in line_vals:
            uom = self.env["uom.uom"].browse(vals["product_uom_id"])
            line = self.line_ids.filtered(
                lambda l: l.product_id.id == vals["product_id"]
                and not l.cancelled
                and l.product_uom_id.category_id == uom.category_id
                and l.actual_supplier_id.id == vals.get("actual_supplier_id", False)
                and l.hlv_backorder == bool(vals.get("hlv_backorder"))
                and (not l.hlv_backorder or l.date_required == vals.get("date_required"))
            )[:1]
            if line:
                extra = {k: v for k, v in vals.items() if k.startswith(CHOICE_FIELD_PREFIXES)}
                line.write(dict(
                    extra,
                    product_qty=line.product_qty + uom._compute_quantity(vals["product_qty"], line.product_uom_id),
                ))
            else:
                line = Line.create(dict(vals, request_id=self.id))
            result.append(line)
        return result

    @api.model
    def _lines_message(self, title, line_vals):
        items = Markup("").join(
            Markup("<li>%s: +%s</li>") % (vals["name"], vals["product_qty"]) for vals in line_vals
        )
        return Markup("<p>%s</p><ul>%s</ul>") % (title, items)

    @api.depends("line_ids")
    def _compute_hlv_inquiry_ids(self):
        Inquiry = self.env["hlv.vendor.inquiry"]
        for request in self:
            request.hlv_inquiry_ids = Inquiry.search([
                ("line_ids.request_line_ids", "in", request.line_ids.ids),
            ]) if request.line_ids else Inquiry

    @api.depends("hlv_inquiry_ids")
    def _compute_hlv_inquiry_count(self):
        for request in self:
            request.hlv_inquiry_count = len(request.hlv_inquiry_ids)

    def action_view_inquiries(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "hlv_vendor_quotation.action_vendor_inquiry"
        )
        action["domain"] = [("id", "in", self.hlv_inquiry_ids.ids)]
        return action

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


class PurchaseRequestLine(models.Model):
    _inherit = "purchase.request.line"

    # Phần NCC hẹn giao sau (NCC thiếu hàng, hẹn ngày): dòng riêng, "Ngày cần" = ngày hẹn — wizard Tạo
    # RFQ tách thành dòng đơn mua riêng theo ngày (wizard/request_rfq_wizard.py).
    hlv_backorder = fields.Boolean(string="Phần NCC hẹn giao", readonly=True, copy=False)

    def _hlv_remaining_qty(self):
        """Số lượng dòng YCMH còn phải mua: yêu cầu − đã lên đơn mua (purchased_qty của
        purchase_request: cộng dòng đơn mua chưa huỷ, quy về ĐVT của YCMH). Không âm."""
        self.ensure_one()
        line = self.sudo()
        return max(0.0, line.product_qty - line.purchased_qty)

    def _hlv_fully_ordered(self):
        """Đã lên đơn mua ĐỦ số lượng — mặt hàng khoá, không đổi NCC được nữa.

        Còn thiếu thì mở: NCC báo hết hàng / chỉ giao được một phần sau khi đã đặt, thu mua sửa
        số lượng dòng đơn mua xuống đúng số NCC giao được (về 0 nếu hết hẳn — đơn mua đã xác
        nhận không xoá được dòng, mà huỷ cả đơn thì hỏng mặt hàng khác), rồi sale chọn NCC
        cho phần còn lại. Chưa có dòng đơn mua nào → chưa khoá.
        """
        self.ensure_one()
        line = self.sudo()
        if not line.purchase_lines.filtered(lambda l: l.state != "cancel"):
            return False
        rounding = line.product_uom_id.rounding or 0.01
        return float_compare(line.purchased_qty, line.product_qty, precision_rounding=rounding) >= 0
