# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from ..services.price_reuse import apply_valid_prices
from ..services.notify import post_internal
from .vendor_quote_utils import clean_ref, format_vn_number, inquiry_close_day, normalize_origin, request_qty

# Cài đặt → Mua hàng → Hỏi giá NCC: sale được sửa hạn báo giá trên ngăn phiếu. Mặc định tắt.
SALE_EDIT_DEADLINE_PARAM = "hlv_vendor_quotation.sale_edit_deadline"

# Sai số so SL (ĐVT có số lẻ): chênh dưới mức này coi như bằng.
QTY_EPSILON = 1e-6
# Dòng phiếu → dòng báo giá NCC: các trường NCC được hỏi, sửa ở phiếu thì báo giá đổi theo (VendorInquiryLine.write).
QUOTE_SYNC_FIELDS = ("name", "product_qty", "product_uom_id")

SALE_STATUS = [
    ("waiting", "Chờ NCC báo giá"),
    ("quoted", "NCC đã báo giá"),
    ("requested", "Đã lên YCMH"),
    ("partial", "Lên YCMH một phần"),
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
    # Số cơ hội bên CRM sale gõ tay — tìm lại mọi báo giá NCC của một cơ hội. Không đặt tên "origin":
    # báo giá NCC đã có origin = Tài liệu nguồn của YCMH (số đơn bán), hai thứ khác nhau.
    opportunity_ref = fields.Char(string="Số cơ hội", index=True, tracking=True)
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

    @api.depends("state", "quote_ids.state", "line_ids.need_qty", "line_ids.quote_line_ids.selected",
                 "line_ids.quote_line_ids.chosen_qty")
    def _compute_sale_status(self):
        for inquiry in self:
            if inquiry.state == "requested" and any(line._hlv_shortage() for line in inquiry.line_ids):
                # Đã lên YCMH phần có NCC, còn sản phẩm thiếu SL — hỏi thêm NCC cho phần thiếu.
                inquiry.sale_status = "partial"
            elif inquiry.state in ("requested", "closed", "cancel"):
                inquiry.sale_status = inquiry.state
            elif any(q.state in ("quoted", "done") for q in inquiry.quote_ids):
                inquiry.sale_status = "quoted"
            else:
                inquiry.sale_status = "waiting"

    @api.depends("quote_ids.state", "line_ids.quote_line_ids.selected")
    def _compute_counts(self):
        for inquiry in self:
            inquiry.quoted_count = len(inquiry.quote_ids.filtered(lambda q: q.state in ("quoted", "done")))
            inquiry.chosen_count = len(inquiry.line_ids.filtered("chosen_line_ids"))

    @api.depends("line_ids.request_line_ids")
    def _compute_request_ids(self):
        for inquiry in self:
            inquiry.request_ids = inquiry.line_ids.request_line_ids.request_id

    @api.depends("line_ids.request_line_ids.purchase_lines.order_id")
    def _compute_purchase_order_ids(self):
        for inquiry in self:
            # Dòng YCMH có thể bị gộp chung với hàng của phiếu khác — chỉ lấy đơn mua của NCC
            # được hỏi trong phiếu này, và đã xác nhận.
            inquiry.purchase_order_ids = inquiry._hlv_vendor_orders().filtered(lambda o: o.state in ("purchase", "done"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Mới") == "Mới":
                vals["name"] = self.env["ir.sequence"].next_by_code("hlv.vendor.inquiry") or "Mới"
        return super().create(vals_list)

    @api.model
    def _create_with_quotes(self, vendors, line_vals, sale_code, sale_order=None,
                            date_deadline=False, note=False, opportunity_ref="", vendor_products=None):
        """Tạo phiếu + mỗi NCC một báo giá (mở ngay cho NCC).

        line_vals: [{product_id, name, product_qty, product_uom_id}]. vendors: res.partner,
        gộp về công ty NCC. opportunity_ref: số cơ hội CRM (tuỳ chọn).
        vendor_products: {id công ty NCC: set(product_id)} — mỗi NCC chỉ được hỏi các mặt hàng đó (không
        phải NCC nào cũng bán mọi mã); None → mọi NCC hỏi mọi mặt hàng. Mặt hàng không NCC nào hỏi → lỗi.
        """
        if not line_vals:
            raise UserError(_("Chọn ít nhất một sản phẩm cần hỏi giá."))
        vendors = vendors.commercial_partner_id
        if not vendors:
            raise UserError(_("Chọn ít nhất một nhà cung cấp."))
        inquiry = self.create({
            "sale_code": sale_code or False,
            # Lấy hàng từ đơn bán thì gắn luôn đơn đó; lấy từ cơ hội CRM thì gắn sau, lúc lên YCMH.
            "sale_order_id": sale_order.id if sale_order else False,
            "date_deadline": date_deadline,
            "note": note,
            "opportunity_ref": clean_ref(opportunity_ref) or False,
            "line_ids": [
                Command.create(dict(vals, sequence=index))
                for index, vals in enumerate(line_vals, start=1)
            ],
        })
        if vendor_products is None:
            inquiry._add_vendors(vendors)
            return inquiry
        wanted = {}
        for vendor_id, product_ids in vendor_products.items():
            wanted.setdefault(vendors.browse(vendor_id).commercial_partner_id.id, set()).update(product_ids)
        orphans = inquiry.line_ids.filtered(
            lambda l: not any(l.product_id.id in wanted.get(v.id, ()) for v in vendors))
        if orphans:
            raise UserError(_("Chưa chọn NCC nào để hỏi: %s.", ", ".join(orphans.mapped("name"))))
        for vendor in vendors:
            lines = inquiry.line_ids.filtered(lambda l, v=vendor: l.product_id.id in wanted.get(v.id, ()))
            if lines:
                inquiry._add_vendors(vendor, lines)
        return inquiry

    def _add_vendors(self, vendors, lines=None, date_deadline=False, note=None):
        """Gửi phiếu cho thêm NCC. NCC đã có báo giá (chưa huỷ) trong phiếu thì bỏ qua.

        lines: dòng phiếu cần hỏi (mặc định mọi dòng) — dòng đã lên đơn mua đủ thì bỏ. date_deadline,
        note: hạn và lời nhắn của các báo giá mới; trống → theo phiếu. Trả các báo giá vừa tạo.
        """
        self.ensure_one()
        if self.state not in ("open", "requested"):
            raise UserError(_("Phiếu %s đã đóng hoặc đã huỷ — lập phiếu mới để hỏi giá.", self.name))
        lines = (self.line_ids if lines is None else lines).filtered(lambda l: not l.locked)
        if not lines:
            raise UserError(_("Chọn ít nhất một sản phẩm chưa lên đơn mua."))
        asked = self.quote_ids.filtered(lambda q: q.state != "cancel").access_id.partner_id
        new_vendors = vendors.commercial_partner_id - asked
        quotes = self.env["hlv.vendor.quote"].create([
            {
                "inquiry_id": self.id,
                "partner_id": vendor.id,
                "sale_order_id": self.sale_order_id.id,
                "date_deadline": date_deadline or self.date_deadline,
                "note": self.note if note is None else note,
                "state": "sent",
                "line_ids": [Command.create(line._quote_line_vals()) for line in lines],
            }
            for vendor in new_vendors
        ])
        # Giá NCC còn hiệu lực (kể cả từ phiếu "Không mua" của sale khác) — điền sẵn, khỏi hỏi lại.
        apply_valid_prices(quotes)
        return quotes

    def action_ask_more_vendors(self, vendors, lines, date_deadline=False, note=""):
        """Sale hỏi thêm NCC cho một số sản phẩm của phiếu — thường vì NCC đã hỏi báo hết hàng.

        Được cả khi phiếu đã lên YCMH (thường để mua phần còn thiếu): NCC mới báo giá xong, sale chọn
        thêm NCC đó (action_choose) rồi "Bổ sung vào YCMH".
        Hạn mới muộn hơn hạn phiếu thì dời hạn phiếu theo — không thì cron đóng phiếu (_close_day)
        tính theo hạn cũ.
        """
        self.ensure_one()
        vendors = vendors.commercial_partner_id
        if not vendors:
            raise UserError(_("Chọn ít nhất một nhà cung cấp."))
        today = self.env["hlv.vendor.quote"]._vendor_today()
        if date_deadline and date_deadline < today:
            raise UserError(_("Hạn báo giá không được trước hôm nay."))
        quotes = self._add_vendors(vendors, lines, date_deadline, (note or "").strip() or self.note)
        if not quotes:
            raise UserError(_(
                "%s đã được hỏi trong phiếu này — xem ở cột NCC của bảng so giá.",
                ", ".join(vendors.mapped("display_name")),
            ))
        if date_deadline and (not self.date_deadline or date_deadline > self.date_deadline):
            self.date_deadline = date_deadline
        self.message_post(body=Markup(_("Hỏi thêm NCC <b>%s</b> cho %s sản phẩm.")) % (
            ", ".join(quotes.partner_id.commercial_partner_id.mapped("display_name")), len(quotes[:1].line_ids),
        ))
        return quotes

    def action_add_products(self, line_vals, quote_products):
        """Sale thêm sản phẩm vào phiếu đã gửi (nút "+ Thêm sản phẩm" trong ngăn phiếu).

        line_vals: [{product_id, name, product_qty, product_uom_id}] như lúc lập phiếu. Sản phẩm đã có trong phiếu
        → cộng dồn SL vào dòng cũ (đổi về ĐVT của dòng), báo giá các NCC đang hỏi món đó tăng SL theo; sản phẩm mới →
        dòng mới. quote_products: {id báo giá đang mở của phiếu: set(product_id)} — NCC nào hỏi món nào, sale tự tick
        (không mặc định hỏi ai); sản phẩm mới phải hỏi ít nhất một NCC. Dòng cộng dồn lấy luôn mô tả mới (tên sản phẩm
        sale vừa chọn) — mô tả cũ có thể đã lỗi thời, sale nhìn bảng so giá không nhận ra món vừa thêm.
        Trả {"added": dòng mới, "merged": [(dòng cộng dồn, SL trước khi cộng)]}.
        """
        self.ensure_one()
        if self.state not in ("open", "requested"):
            raise UserError(_("Phiếu %s đã đóng hoặc đã huỷ — lập phiếu mới để hỏi giá.", self.name))
        if not line_vals:
            raise UserError(_("Chọn ít nhất một sản phẩm."))
        quotes = self.quote_ids.filtered(lambda q: q.state in ("sent", "quoted"))
        if set(quote_products) - set(quotes.ids):
            raise UserError(_("Có báo giá NCC đã đóng / huỷ — mở lại phiếu rồi chọn lại NCC."))
        Line = self.env["hlv.vendor.inquiry.line"]
        by_product = {line.product_id.id: line for line in self.line_ids}
        sequence = max(self.line_ids.mapped("sequence") or [0])
        added = merged = Line
        before = {}
        for vals in line_vals:
            line = by_product.get(vals["product_id"])
            if line:
                uom = self.env["uom.uom"].browse(vals["product_uom_id"])
                before.setdefault(line.id, line.product_qty)
                line._hlv_add_qty(uom._compute_quantity(vals["product_qty"], line.product_uom_id)
                                  if uom and line.product_uom_id else vals["product_qty"])
                line._hlv_rename(vals["name"])
                merged |= line
            else:
                sequence += 1
                line = Line.create(dict(vals, inquiry_id=self.id, sequence=sequence))
                by_product[line.product_id.id] = line
                added |= line
        asked = {product_id for product_ids in quote_products.values() for product_id in product_ids}
        orphans = added.filtered(lambda l: l.product_id.id not in asked)
        if orphans:
            raise UserError(_("Chưa chọn NCC nào để hỏi: %s.", ", ".join(orphans.mapped("name"))))
        for quote in quotes:
            open_lines = quote.line_ids.filtered(lambda l: not l.withdrawn).inquiry_line_id
            lines = (added | merged).filtered(
                lambda l, q=quote: l.product_id.id in quote_products.get(q.id, ()) and l not in open_lines and not l.locked)
            if lines:
                quote.action_add_inquiry_lines(lines)
        self.message_post(body=Markup(_("Sale thêm sản phẩm vào phiếu: %s.")) % ", ".join(
            [line.name or line.product_id.display_name for line in added]
            + [_("%s (cộng thêm SL %s → %s)", line.name or line.product_id.display_name,
                 format_vn_number(before[line.id]), format_vn_number(line.product_qty)) for line in merged]))
        return {"added": added, "merged": [(line, before[line.id]) for line in merged]}

    @api.model
    def _hlv_sale_can_edit_deadline(self):
        """Cài đặt có cho sale sửa hạn báo giá trên ngăn phiếu không (SALE_EDIT_DEADLINE_PARAM)."""
        return self.env["ir.config_parameter"].sudo().get_param(SALE_EDIT_DEADLINE_PARAM) == "True"

    def action_set_deadline(self, date_deadline):
        """Sale đổi hạn báo giá của phiếu (chỉ khi Cài đặt cho phép — SALE_EDIT_DEADLINE_PARAM, controller kiểm).
        Ghi phiếu + các báo giá NCC còn mở (chờ / đã báo, kể cả đã quá hạn — dời hạn là mở lại cho NCC báo).
        Hạn trước hôm nay (giờ VN) → lỗi."""
        self.ensure_one()
        if self.state not in ("open", "requested"):
            raise UserError(_("Phiếu %s đã đóng hoặc đã huỷ.", self.name))
        today = self.env["hlv.vendor.quote"]._vendor_today()
        if not date_deadline or date_deadline < today:
            raise UserError(_("Hạn báo giá không được trước hôm nay."))
        old = self.date_deadline
        self.date_deadline = date_deadline
        self.quote_ids.sudo().filtered(lambda q: q.state in ("sent", "quoted")).write({"date_deadline": date_deadline})
        self.message_post(body=_("Sale đổi hạn báo giá: %(old)s → %(new)s.",
                                 old=old.strftime("%d/%m/%Y") if old else _("(trống)"),
                                 new=date_deadline.strftime("%d/%m/%Y")))

    def action_set_opportunity(self, opportunity_ref):
        """Sale ghi / sửa số cơ hội sau khi lập phiếu (thường có số cơ hội sau khi đã hỏi giá).
        Rỗng = bỏ số cơ hội. Phiếu đã huỷ thì không sửa."""
        for inquiry in self:
            if inquiry.state == "cancel":
                raise UserError(_("Phiếu %s đã huỷ.", inquiry.name))
        self.write({"opportunity_ref": clean_ref(opportunity_ref) or False})

    def _hlv_vendor_orders(self):
        """Đơn mua (mọi trạng thái) sinh từ YCMH của phiếu — chỉ của NCC được hỏi trong phiếu: dòng YCMH có
        thể bị gộp chung với hàng của phiếu khác."""
        self.ensure_one()
        vendors = self.quote_ids.partner_id.commercial_partner_id
        orders = self.line_ids.request_line_ids.sudo().purchase_lines.order_id
        return orders.filtered(lambda o: o.partner_id.commercial_partner_id in vendors)

    def _hlv_live_requests(self):
        """YCMH lập từ trang hỏi giá của phiếu, chưa bị từ chối — nơi sale còn sửa người yêu cầu / mã đơn
        hàng. Không đụng YCMH đi từ MISA: còn chờ duyệt thì extension MISA đồng bộ đè lại."""
        self.ensure_one()
        return self.request_ids.sudo().filtered(lambda r: r.hlv_from_quote_page and r.state != "rejected")

    def _hlv_order_ref_targets(self):
        """(YCMH, đơn mua chưa huỷ) nhận mã đơn hàng của khách."""
        return self._hlv_live_requests(), self._hlv_vendor_orders().filtered(lambda o: o.state != "cancel")

    def hlv_order_ref(self):
        """Mã đơn hàng đang chung của YCMH + đơn mua của phiếu; chưa có nơi nào / mỗi nơi một mã → ""."""
        requests, orders = self._hlv_order_ref_targets()
        values = {r.origin or "" for r in requests} | {o.origin or "" for o in orders}
        return values.pop() if len(values) == 1 else ""

    def action_set_order_ref(self, origin):
        """Sale ghi mã đơn hàng của khách cho cả phiếu — được cả khi YCMH còn chờ duyệt, chưa có đơn mua:
        ghi vào Tài liệu gốc của YCMH (đơn mua thu mua tạo sau lấy origin từ dòng YCMH — wizard Tạo RFQ)
        và của các đơn mua đã có. Mã trùng đúng số một đơn bán thì ghi luôn "Đơn bán hàng liên quan" của YCMH +
        đơn bán của phiếu (_hlv_sale_order_from_origin). Trả các đơn mua đã ghi."""
        self.ensure_one()
        if self.state == "cancel":
            raise UserError(_("Phiếu %s đã huỷ.", self.name))
        requests, orders = self._hlv_order_ref_targets()
        if not requests and not orders:
            raise UserError(_("Phiếu chưa lên YCMH — gắn đơn bán ở bước lên YCMH."))
        origin = normalize_origin(origin)
        sale_order = self._hlv_sale_order_from_origin(origin)
        author = self.env.user.partner_id
        for purchase_request in requests.filtered(lambda r: (r.origin or "") != origin):
            old = purchase_request.origin or ""
            purchase_request.origin = origin or False
            post_internal(purchase_request, Markup(_(
                "Sale cập nhật Tài liệu gốc (mã đơn hàng) từ phiếu hỏi giá %s: <b>%s</b> → <b>%s</b>.")) % (
                self.name, old or _("(trống)"), origin or _("(trống)")), author)
        if sale_order:
            self._hlv_link_sale_order(sale_order, requests, author)
        orders._hlv_set_origin(origin)
        return orders

    def _hlv_sale_order_from_origin(self, origin):
        """Đơn bán có số trùng ĐÚNG một mã trong origin (đã normalize_origin). Không mã nào là số đơn bán (mã khách tự
        đặt) → rỗng. Trùng từ hai đơn bán trở lên → UserError: nghiệp vụ một YCMH chỉ gắn một đơn bán."""
        codes = [code for code in (origin or "").split(", ") if code]
        sale_orders = self.env["sale.order"].sudo().search([("name", "in", codes)]) if codes else self.env["sale.order"]
        if len(sale_orders) > 1:
            raise UserError(_("Một YCMH chỉ gắn một đơn bán — %s là %s đơn bán khác nhau. Chỉ để một số đơn bán.",
                              ", ".join(sale_orders.mapped("name")), len(sale_orders)))
        return sale_orders

    def _hlv_link_sale_order(self, sale_order, requests, author):
        """Ghi đơn bán vào phiếu + "Đơn bán hàng liên quan" của YCMH còn sửa được (YCMH Hoàn thành / Từ chối khoá
        trường này trên form — không ghi đè từ đây)."""
        if self.sale_order_id != sale_order:
            self.sale_order_id = sale_order
        for purchase_request in requests.filtered(
                lambda r: r.state not in ("done", "rejected") and r.sale_order_id != sale_order):
            old = purchase_request.sale_order_id.name or _("(trống)")
            purchase_request.sale_order_id = sale_order
            post_internal(purchase_request, Markup(_(
                "Sale cập nhật Đơn bán hàng liên quan từ phiếu hỏi giá %s: <b>%s</b> → <b>%s</b>.")) % (
                self.name, old, sale_order.name), author)

    def action_set_sale_code(self, code):
        """Đổi mã sale của phiếu; YCMH lập từ trang hỏi giá của phiếu ghi theo làm "Người yêu cầu".
        code: mã ĐÃ kiểm quyền ở controller (sale_scope.validate_sale_code)."""
        self.ensure_one()
        code = (code or "").strip()
        if not code:
            raise UserError(_("Chọn mã sale."))
        if self.state == "cancel":
            raise UserError(_("Phiếu %s đã huỷ.", self.name))
        if code != (self.sale_code or ""):
            self.sale_code = code
        label = self.env["hlv.vendor.sale.contact"]._requester_label(code)
        self._hlv_live_requests().filtered(lambda r: r.x_misa_requested_by != label).write({"x_misa_requested_by": label})

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

    def action_create_request(self, sale_order=None, quantities=None, settle_line_ids=(), separate_backorder=False,
                              line_notes=None, request_vals=None):
        """Đưa các NCC đã chọn mà CHƯA nằm trên YCMH lên YCMH — mỗi NCC một dòng (NCC thiếu hàng có
        hẹn thì thêm dòng phần hẹn), kèm giá + NCC.

        Gọi được nhiều lần: lên phần đã chọn; chọn thêm NCC sau (phần còn thiếu) thì bổ sung. Bổ sung
        vào YCMH gần nhất của phiếu nếu còn chưa duyệt; không thì theo đơn bán (gộp vào YCMH chưa
        duyệt của đơn) hoặc tạo YCMH mới. Còn thiếu SL vẫn lên phần đã có — phiếu "Lên YCMH một phần".
        quantities: {id dòng báo giá: SL mua} sale sửa ở bảng tóm tắt (khách đổi số lượng sau khi hỏi giá).
        settle_line_ids: dòng phiếu sale chốt "khách chỉ mua chừng này" — SL cần mua = SL đã chọn,
        hết thiếu. SL hỏi trên phiếu giữ nguyên: NCC báo giá theo số đó.
        separate_backorder: phần NCC hẹn giao ra đơn mua riêng (mặc định gộp chung đơn với hàng có sẵn) — ghi
        lên dòng YCMH phần hẹn làm mặc định cho wizard Tạo RFQ, thu mua đổi được.
        line_notes: {id dòng báo giá: ghi chú} → "Ghi chú" (misa_note) của dòng YCMH (cả phần hẹn); request_vals: địa điểm giao,
        kho nhận, ngày sale muốn nhận hàng của YCMH (purchase_request._add_request_lines).
        """
        self.ensure_one()
        if self.state in ("cancel", "closed"):
            raise UserError(_("Phiếu %s đã đóng — lập phiếu mới, giá còn hiệu lực sẽ được dùng lại.", self.name))
        pending = self.line_ids.chosen_line_ids.filtered(lambda l: l._hlv_needs_request())
        if not pending:
            raise UserError(_("Không có NCC nào đã chọn mà chưa lên YCMH."))
        # Mã sale là "Người yêu cầu" của YCMH — thu mua / MISA biết hàng mua cho sale nào.
        if not self.sale_code:
            raise UserError(_("Chọn mã sale (người yêu cầu) trước khi lên YCMH."))
        asked_before = {line.id: line._hlv_chosen_total() for line in self.line_ids}
        for quote_line in pending.filtered(lambda l: l.id in (quantities or {})):
            qty = request_qty(quantities[quote_line.id], quote_line.chosen_qty)
            quote_line.action_set_buy_qty(qty if qty is not None else 0.0)
        settled = self.line_ids.filtered(lambda l: l.id in set(settle_line_ids or ()))._hlv_settle()
        order = sale_order or self.sale_order_id
        notes = {key: (text or "").strip() for key, text in (line_notes or {}).items() if (text or "").strip()}
        parts = [(quote_line, dict(vals, **({"hlv_separate_po": True} if is_backorder and separate_backorder else {}),
                                   **({"misa_note": notes[quote_line.id]} if quote_line.id in notes else {})), is_backorder)
                 for quote_line in pending for vals, is_backorder in quote_line._hlv_request_parts()]
        request, request_lines, merged = self.env["purchase.request"]._add_request_lines(
            [vals for _quote_line, vals, _bo in parts],
            order=order or None,
            source=self.name,
            requester_code=self.sale_code or "",
            merge_into=self.request_id,
            request_vals=request_vals,
        )
        # _add_request_lines trả dòng YCMH theo đúng thứ tự dòng đã đưa vào.
        self.env["hlv.vendor.quote.line"]._hlv_link_request_lines([
            (quote_line, request_line, is_backorder)
            for (quote_line, _vals, is_backorder), request_line in zip(parts, request_lines, strict=True)
        ])
        self.write({
            "state": "requested",
            "request_id": request.id,
            "sale_order_id": order.id if order else False,
        })
        split_note = Markup(" ") + _("Phần NCC hẹn giao: đơn mua riêng.") if separate_backorder and any(
            is_backorder for _q, _v, is_backorder in parts) else ""
        self.message_post(body=Markup(_("%s YCMH <b>%s</b>: %s NCC × sản phẩm đã chọn.")) % (
            _("Gộp vào") if merged else _("Đã tạo"), request.name, len(pending),
        ) + split_note + self.line_ids._changed_qty_message(asked_before) + settled)
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
    # SL sale cần mua (mặc định = SL hỏi). Giảm khi sale chốt "khách chỉ mua chừng này" lúc lên YCMH —
    # phần còn thiếu = SL cần mua − tổng SL mua của các NCC đã chọn.
    need_qty = fields.Float(string="SL cần mua", digits="Product Unit of Measure")
    quote_line_ids = fields.One2many("hlv.vendor.quote.line", "inquiry_line_id", string="Giá các NCC")
    chosen_line_ids = fields.Many2many(
        "hlv.vendor.quote.line", string="NCC đã chọn", compute="_compute_chosen_line_ids",
        help="Một sản phẩm chọn được nhiều NCC, mỗi NCC một SL mua.",
    )
    # Dòng YCMH của mọi NCC (cả đã huỷ / YCMH bị từ chối — để hiện lịch sử). Lưu để tìm ngược từ YCMH /
    # đơn mua về phiếu (domain "line_ids.request_line_ids").
    request_line_ids = fields.Many2many(
        "purchase.request.line", "hlv_vendor_inquiry_line_request_rel", "inquiry_line_id", "request_line_id",
        string="Dòng YCMH", compute="_compute_request_line_ids", store=True,
    )
    locked = fields.Boolean(
        string="Đã lên đơn mua", compute="_compute_locked",
        help="Đã lên RFQ/đơn mua đủ SL cần mua: không chọn thêm NCC. NCC giao thiếu: thu mua sửa số lượng "
             "dòng đơn mua xuống, sale giảm SL mua của NCC đó — phần còn thiếu mở ra để chọn NCC khác.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("need_qty", vals.get("product_qty", 0.0))
        return super().create(vals_list)

    def write(self, vals):
        result = super().write(vals)
        synced = {field: vals[field] for field in QUOTE_SYNC_FIELDS if field in vals}
        if synced:
            self._hlv_sync_quote_lines(synced)
        return result

    def _hlv_sync_quote_lines(self, vals):
        """Mô tả / SL / ĐVT dòng phiếu là cái NCC được hỏi: sửa ở phiếu thì mọi báo giá NCC của món này đổi theo — kể cả
        dòng đang thu hồi ("Hỏi lại" bật lại đúng dòng cũ, không được mang mô tả / SL cũ). Trừ báo giá đã đóng / huỷ và
        dòng đã lên đơn mua (số đã đặt nằm trên YCMH / đơn mua). Sale không có quyền ghi báo giá NCC → sudo."""
        self.quote_line_ids.filtered(
            lambda l: l.quote_id.state in ("sent", "quoted") and not l.vendor_locked).sudo().write(vals)

    @api.depends("quote_line_ids.request_line_id", "quote_line_ids.backorder_request_line_id")
    def _compute_request_line_ids(self):
        for line in self:
            line.request_line_ids = line.quote_line_ids._hlv_own_request_lines()

    @api.depends("need_qty", "request_line_ids.purchased_qty", "request_line_ids.cancelled",
                 "request_line_ids.purchase_lines.state")
    def _compute_locked(self):
        for line in self:
            ordered = sum(line.quote_line_ids._hlv_live_request_lines().mapped("purchased_qty"))
            line.locked = bool(line.request_line_ids) and ordered >= line.need_qty - QTY_EPSILON

    @api.depends("quote_line_ids.selected")
    def _compute_chosen_line_ids(self):
        for line in self:
            line.chosen_line_ids = line.quote_line_ids.filtered("selected")

    def _hlv_chosen_total(self):
        """Tổng SL mua đã chia cho các NCC đang chọn."""
        self.ensure_one()
        return sum(self.chosen_line_ids.mapped("chosen_qty"))

    def _hlv_shortage(self):
        """Phần còn thiếu chưa chia cho NCC nào (không âm)."""
        self.ensure_one()
        return max(0.0, self.need_qty - self._hlv_chosen_total())

    def _hlv_live_request_lines(self):
        """Dòng YCMH còn hiệu lực của mọi NCC đang chọn."""
        return self.chosen_line_ids._hlv_live_request_lines()

    def _hlv_settle(self):
        """Sale chốt "khách chỉ mua chừng này": SL cần mua = SL đã chọn (hết thiếu). Trả dòng chatter."""
        changed = self.filtered(lambda l: l._hlv_shortage() > QTY_EPSILON)
        if not changed:
            return Markup("")
        items = Markup("").join(
            Markup("<li>%s: %s → %s %s</li>") % (
                line.name or line.product_id.display_name, format_vn_number(line.need_qty),
                format_vn_number(line._hlv_chosen_total()), line.product_uom_id.name or "",
            ) for line in changed
        )
        for line in changed:
            line.need_qty = line._hlv_chosen_total()
        return Markup("<p>%s</p><ul>%s</ul>") % (_("Khách chỉ mua chừng này — SL cần mua:"), items)

    def _hlv_add_qty(self, qty):
        """Cộng thêm qty (ĐVT của dòng) vào SL hỏi + SL cần mua (báo giá NCC đổi theo — write); báo giá NCC đang hỏi món
        này ghi chú cho NCC biết."""
        self.ensure_one()
        before = self.product_qty
        self.write({"product_qty": before + qty, "need_qty": self.need_qty + qty})
        for quote_line in self.quote_line_ids.filtered(
                lambda l: l.quote_id.state in ("sent", "quoted") and not l.withdrawn and not l.vendor_locked).sudo():
            post_internal(quote_line.quote_id, Markup(_("Sale tăng SL hỏi <b>%s</b>: %s → %s %s.")) % (
                self.name or self.product_id.display_name, format_vn_number(before), format_vn_number(self.product_qty),
                self.product_uom_id.name or ""), self.env.user.partner_id)

    def _hlv_rename(self, name):
        """Mô tả dòng đổi thành name — sale vừa chọn lại đúng sản phẩm (báo giá NCC đổi theo — write)."""
        self.ensure_one()
        if name and name != self.name:
            self.name = name

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

    def _changed_qty_message(self, before):
        """Dòng chatter: sản phẩm mà tổng SL mua của các NCC khác SL đã hỏi, sau khi sale sửa ở bảng tóm
        tắt (before: {id dòng: tổng SL mua trước khi sửa}). "" nếu không dòng nào đổi so với trước."""
        changed = self.filtered(
            lambda line: abs(line._hlv_chosen_total() - before.get(line.id, 0.0)) > QTY_EPSILON
            and abs(line._hlv_chosen_total() - line.product_qty) > QTY_EPSILON
        )
        if not changed:
            return Markup("")
        items = Markup("").join(
            Markup("<li>%s: %s → %s %s</li>") % (
                line.name or line.product_id.display_name, format_vn_number(line.product_qty),
                format_vn_number(line._hlv_chosen_total()), line.product_uom_id.name or "",
            ) for line in changed
        )
        return Markup("<p>%s</p><ul>%s</ul>") % (_("Số lượng mua khác số lượng đã hỏi giá:"), items)
