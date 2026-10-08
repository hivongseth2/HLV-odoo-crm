# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from ..services.price_reuse import apply_valid_prices
from .vendor_quote_utils import inquiry_close_day

SALE_STATUS = [
    ("waiting", "Chờ NCC báo giá"),
    ("quoted", "NCC đã báo giá"),
    ("requested", "Đã lên YCMH"),
    ("closed", "Không mua"),
    ("cancel", "Đã huỷ"),
]
# Lý do đóng "Không mua" — "auto": cron đóng khi giá NCC đã hết hiệu lực (_cron_auto_close).
CLOSE_REASONS = [
    ("customer", "Khách không lấy"),
    ("price", "Giá cao"),
    ("lead_time", "Giao lâu"),
    ("stock", "NCC hết hàng"),
    ("other", "Khác"),
    ("auto", "Tự đóng — hết hiệu lực giá"),
]


class VendorInquiry(models.Model):
    """Phiếu hỏi giá: một sale hỏi giá một danh sách SẢN PHẨM, gửi cho nhiều NCC.

    Sale hỏi giá theo sản phẩm chứ không theo YCMH: phiếu sinh mỗi NCC một báo giá
    (hlv.vendor.quote), sale so giá và CHỌN NCC cho từng sản phẩm, rồi từ lựa chọn đó sinh
    YCMH (giá + NCC đã chọn ghi sẵn vào dòng YCMH để nút "Tạo RFQ" dùng luôn).
    Chuỗi liên kết: phiếu → báo giá NCC → YCMH → đơn mua; NCC thấy được đơn mua nào sinh
    ra từ báo giá của mình.
    """

    _name = "hlv.vendor.inquiry"
    _description = "Phiếu hỏi giá nhà cung cấp"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(string="Số phiếu", required=True, readonly=True, copy=False, default="Mới")
    sale_code = fields.Char(string="Mã sale", index=True, tracking=True)
    user_id = fields.Many2one("res.users", string="Người tạo", default=lambda self: self.env.user)
    company_id = fields.Many2one(
        "res.company", string="Công ty", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    sale_order_id = fields.Many2one("sale.order", string="Đơn bán", index=True, tracking=True)
    request_id = fields.Many2one(
        "purchase.request", string="YCMH gần nhất", readonly=True, index=True,
        ondelete="set null", tracking=True,
    )
    # Một phiếu có thể lên nhiều YCMH (lên trước phần đã chọn, bổ sung phần chọn sau).
    request_ids = fields.Many2many(
        "purchase.request", string="Yêu cầu mua hàng", compute="_compute_request_ids"
    )
    date_deadline = fields.Date(string="Hạn báo giá")
    note = fields.Text(string="Lời nhắn gửi NCC")
    state = fields.Selection(
        [("open", "Đang hỏi giá"), ("requested", "Đã lên YCMH"), ("closed", "Không mua"), ("cancel", "Đã huỷ")],
        string="Trạng thái", default="open", required=True, tracking=True,
    )
    close_reason = fields.Selection(CLOSE_REASONS, string="Lý do không mua", readonly=True, tracking=True)
    close_note = fields.Char(string="Ghi chú không mua", readonly=True)
    sale_status = fields.Selection(
        SALE_STATUS, string="Tình trạng", compute="_compute_sale_status", store=True, index=True
    )
    line_ids = fields.One2many("hlv.vendor.inquiry.line", "inquiry_id", string="Sản phẩm")
    quote_ids = fields.One2many("hlv.vendor.quote", "inquiry_id", string="Báo giá NCC")
    quoted_count = fields.Integer(string="NCC đã báo giá", compute="_compute_counts")
    chosen_count = fields.Integer(string="Sản phẩm đã chọn NCC", compute="_compute_counts")
    purchase_order_ids = fields.Many2many(
        "purchase.order", string="Đơn mua", compute="_compute_purchase_order_ids"
    )

    @api.depends("state", "quote_ids.state")
    def _compute_sale_status(self):
        for inquiry in self:
            if inquiry.state in ("requested", "closed", "cancel"):
                inquiry.sale_status = inquiry.state
            elif any(q.state in ("quoted", "done") for q in inquiry.quote_ids):
                inquiry.sale_status = "quoted"
            else:
                inquiry.sale_status = "waiting"

    @api.depends("quote_ids.state", "line_ids.chosen_line_id")
    def _compute_counts(self):
        for inquiry in self:
            inquiry.quoted_count = len(inquiry.quote_ids.filtered(lambda q: q.state in ("quoted", "done")))
            inquiry.chosen_count = len(inquiry.line_ids.filtered("chosen_line_id"))

    @api.depends("line_ids.request_line_id")
    def _compute_request_ids(self):
        for inquiry in self:
            inquiry.request_ids = inquiry.line_ids.request_line_id.request_id

    @api.depends("line_ids.request_line_id.purchase_lines.order_id")
    def _compute_purchase_order_ids(self):
        for inquiry in self:
            # Dòng YCMH có thể bị gộp chung với hàng của phiếu khác — chỉ lấy đơn mua của NCC
            # mà phiếu này đã chọn, và đã xác nhận.
            chosen_vendors = inquiry.line_ids.chosen_line_id.partner_id.commercial_partner_id
            orders = inquiry.line_ids.request_line_id.sudo().purchase_lines.order_id
            inquiry.purchase_order_ids = orders.filtered(
                lambda o: o.state in ("purchase", "done")
                and o.partner_id.commercial_partner_id in chosen_vendors
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Mới") == "Mới":
                vals["name"] = self.env["ir.sequence"].next_by_code("hlv.vendor.inquiry") or "Mới"
        return super().create(vals_list)

    @api.model
    def _create_with_quotes(self, vendors, line_vals, sale_code, sale_order=None,
                            date_deadline=False, note=False):
        """Tạo phiếu + mỗi NCC một báo giá (mở ngay cho NCC), cùng danh sách sản phẩm.

        line_vals: [{product_id, name, product_qty, product_uom_id}]. vendors: res.partner,
        gộp về công ty NCC.
        """
        if not line_vals:
            raise UserError(_("Chọn ít nhất một sản phẩm cần hỏi giá."))
        vendors = vendors.commercial_partner_id
        if not vendors:
            raise UserError(_("Chọn ít nhất một nhà cung cấp."))
        inquiry = self.create({
            "sale_code": sale_code or False,
            "sale_order_id": sale_order.id if sale_order else False,
            "date_deadline": date_deadline,
            "note": note,
            "line_ids": [
                Command.create(dict(vals, sequence=index))
                for index, vals in enumerate(line_vals, start=1)
            ],
        })
        inquiry._add_vendors(vendors)
        return inquiry

    def _add_vendors(self, vendors):
        """Gửi phiếu cho thêm NCC. NCC đã có báo giá (chưa huỷ) trong phiếu thì bỏ qua."""
        self.ensure_one()
        if self.state != "open":
            raise UserError(_("Phiếu %s không còn ở trạng thái hỏi giá.", self.name))
        asked = self.quote_ids.filtered(lambda q: q.state != "cancel").access_id.partner_id
        new_vendors = vendors.commercial_partner_id - asked
        quotes = self.env["hlv.vendor.quote"].create([
            {
                "inquiry_id": self.id,
                "partner_id": vendor.id,
                "sale_order_id": self.sale_order_id.id,
                "date_deadline": self.date_deadline,
                "note": self.note,
                "state": "sent",
                "line_ids": [Command.create(line._quote_line_vals()) for line in self.line_ids],
            }
            for vendor in new_vendors
        ])
        # Giá NCC còn hiệu lực (kể cả từ phiếu "Không mua" của sale khác) — điền sẵn, khỏi hỏi lại.
        apply_valid_prices(quotes)
        return quotes

    def _apply_reuse_choices(self, choices):
        """Chọn sẵn giá dùng lại sale đã bấm "Dùng giá này" lúc lập phiếu. choices: {product_id:
        vendor_id}. Chỉ chọn khi dòng báo giá của NCC đó thật sự đã kế thừa giá (giá có thể vừa bị
        phiếu khác giữ / hết hạn giữa lúc xem và lúc gửi). Trả các dòng phiếu KHÔNG chọn được."""
        self.ensure_one()
        missing = self.env["hlv.vendor.inquiry.line"]
        for line in self.line_ids.filtered(lambda l: l.product_id.id in choices):
            vendor_id = choices[line.product_id.id]
            quote_line = line.quote_line_ids.filtered(
                lambda q: q.quote_id.partner_id.commercial_partner_id.id == vendor_id and q.inherited_from_id
            )[:1]
            if quote_line:
                quote_line.action_choose()
            else:
                missing |= line
        return missing

    def action_create_request(self, sale_order=None):
        """Đưa các sản phẩm đã chọn NCC mà CHƯA nằm trong YCMH nào lên YCMH, kèm giá + NCC.

        Gọi được nhiều lần: lần đầu lên phần đã chọn; sản phẩm chọn sau thì bổ sung. Bổ sung
        vào YCMH gần nhất của phiếu nếu nó còn chưa duyệt; không thì theo đơn bán (gộp vào YCMH
        chưa duyệt của đơn nếu có) hoặc tạo YCMH mới. Sản phẩm chưa chọn NCC không lên.
        """
        self.ensure_one()
        if self.state in ("cancel", "closed"):
            raise UserError(_("Phiếu %s đã đóng — lập phiếu mới, giá còn hiệu lực sẽ được dùng lại.", self.name))
        pending = self.line_ids.filtered(lambda l: l.chosen_line_id and not l.request_line_id)
        if not pending:
            raise UserError(_("Không có sản phẩm nào đã chọn NCC mà chưa lên YCMH."))
        order = sale_order or self.sale_order_id
        request, request_lines, merged = self.env["purchase.request"]._add_request_lines(
            [line._request_line_vals() for line in pending],
            order=order or None,
            source=self.name,
            requester_code=self.sale_code or "",
            merge_into=self.request_id,
        )
        # _add_request_lines trả dòng YCMH theo đúng thứ tự dòng đã đưa vào.
        for line, request_line in zip(pending, request_lines, strict=True):
            line.request_line_id = request_line
            line.chosen_line_id.request_line_id = request_line
        self.write({
            "state": "requested",
            "request_id": request.id,
            "sale_order_id": order.id if order else False,
        })
        self.message_post(body=Markup(_("%s YCMH <b>%s</b> từ %s sản phẩm đã chọn NCC.")) % (
            _("Gộp vào") if merged else _("Đã tạo"), request.name, len(pending),
        ))
        return request, merged

    def action_close(self, reason, note=""):
        """Sale đóng phiếu "Không mua": nhu cầu kết thúc, nhưng giá NCC đã báo vẫn giữ (báo giá
        chuyển "Đã đóng" — NCC không sửa nữa, sale khác dùng lại được tới ngày hiệu lực).
        Chỉ phiếu đang hỏi giá; đã lên YCMH thì không đóng được."""
        if reason not in dict(CLOSE_REASONS):
            raise UserError(_("Chọn lý do không mua."))
        for inquiry in self:
            if inquiry.state != "open":
                raise UserError(_("Phiếu %s không còn ở trạng thái hỏi giá.", inquiry.name))
        self.quote_ids.filtered(lambda q: q.state in ("draft", "sent", "quoted")).write({"state": "done"})
        self.write({"state": "closed", "close_reason": reason, "close_note": (note or "").strip()[:255] or False})
        label = dict(CLOSE_REASONS)[reason]
        for inquiry in self:
            inquiry.message_post(body=Markup(_("Đóng phiếu — không mua: <b>%s</b>%s")) % (
                label, Markup(" — %s") % inquiry.close_note if inquiry.close_note else "",
            ))

    def _close_day(self):
        """Ngày cuối phiếu còn mở (vendor_quote_utils.inquiry_close_day)."""
        self.ensure_one()
        quoted = self.quote_ids.filtered(lambda q: q.state in ("quoted", "done"))
        return inquiry_close_day(
            quoted.mapped("price_valid_until"), self.date_deadline,
            self.create_date.date() if self.create_date else None,
        )

    @api.model
    def _cron_auto_close(self):
        """Hằng ngày: phiếu chưa lên YCMH mà qua ngày cuối (giá NCC hết hiệu lực / chưa ai báo
        sau hạn + 7 ngày) thì tự đóng "Không mua" — danh sách gọn, giá vẫn giữ để tra."""
        today = self.env["hlv.vendor.quote"]._vendor_today()
        expired = self.search([("state", "=", "open")]).filtered(
            lambda inquiry: inquiry._close_day() and inquiry._close_day() < today
        )
        if expired:
            expired.action_close("auto")

    def action_cancel(self):
        for inquiry in self:
            if inquiry.state == "requested":
                raise UserError(_("Phiếu %s đã lên YCMH — huỷ YCMH bên thu mua.", inquiry.name))
        self.quote_ids.filtered(lambda q: q.state != "cancel").write({"state": "cancel"})
        self.write({"state": "cancel"})


class VendorInquiryLine(models.Model):
    _name = "hlv.vendor.inquiry.line"
    _description = "Sản phẩm trong phiếu hỏi giá"
    _order = "inquiry_id, sequence, id"

    inquiry_id = fields.Many2one("hlv.vendor.inquiry", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one("product.product", string="Sản phẩm", required=True)
    name = fields.Char(string="Mô tả")
    product_qty = fields.Float(string="Số lượng", digits="Product Unit of Measure")
    product_uom_id = fields.Many2one("uom.uom", string="ĐVT")
    quote_line_ids = fields.One2many("hlv.vendor.quote.line", "inquiry_line_id", string="Giá các NCC")
    chosen_line_id = fields.Many2one(
        "hlv.vendor.quote.line", string="Giá đã chọn", compute="_compute_chosen_line_id", store=True
    )
    request_line_id = fields.Many2one(
        "purchase.request.line", string="Dòng YCMH", readonly=True, ondelete="set null", index=True
    )
    locked = fields.Boolean(
        string="Đã lên đơn mua", compute="_compute_locked",
        help="Dòng YCMH đã lên RFQ/đơn mua đủ số lượng: đổi NCC ở phiếu không đổi được đơn đã tạo. "
             "Thu mua sửa số lượng dòng đơn mua xuống (NCC giao thiếu / hết hàng) thì mở lại cho phần còn thiếu.",
    )

    @api.depends("request_line_id.purchased_qty", "request_line_id.product_qty",
                 "request_line_id.purchase_lines.state")
    def _compute_locked(self):
        for line in self:
            line.locked = bool(line.request_line_id) and line.request_line_id._hlv_fully_ordered()

    @api.depends("quote_line_ids.selected")
    def _compute_chosen_line_id(self):
        for line in self:
            line.chosen_line_id = line.quote_line_ids.filtered("selected")[:1]

    def _quote_line_vals(self):
        self.ensure_one()
        return {
            "sequence": self.sequence,
            "inquiry_line_id": self.id,
            "product_id": self.product_id.id,
            "name": self.name,
            "product_qty": self.product_qty,
            "product_uom_id": self.product_uom_id.id,
        }

    def _request_line_vals(self):
        """Dòng YCMH cho sản phẩm đã chọn NCC — kèm actual_* để wizard Tạo RFQ dùng luôn."""
        self.ensure_one()
        return dict(
            {
                "product_id": self.product_id.id,
                "name": self.name or self.product_id.display_name,
                "product_qty": self.product_qty,
                "product_uom_id": self.product_uom_id.id,
            },
            **self.chosen_line_id._request_line_actual_vals(),
        )
