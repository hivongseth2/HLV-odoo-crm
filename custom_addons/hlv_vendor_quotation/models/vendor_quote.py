# -*- coding: utf-8 -*-
import pytz

from markupsafe import Markup
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.chat_bus import notify_quoted
from ..services.notify import post_internal
from .vendor_quote_utils import default_price_valid_until, match_by_product

# NCC chỉ thấy báo giá đã gửi đi; nháp và đã huỷ là việc nội bộ.
VENDOR_VISIBLE_STATES = ("sent", "quoted", "done")
# Trạng thái theo góc nhìn NCC, theo thứ tự hiện trên tab lọc.
VENDOR_STATUSES = ("waiting", "quoted", "expired", "closed")
VENDOR_EDITABLE_STATUSES = ("waiting", "quoted")
DEFAULT_TZ = "Asia/Ho_Chi_Minh"


class VendorQuote(models.Model):
    """Yêu cầu báo giá gửi một NCC cho các mặt hàng của một YCMH.

    Không dùng RFQ nháp (purchase.order) của core "Đơn dự trù": mỗi PO tạo ra sẽ bắn
    Zalo "đơn mua mới", ăn số PO và làm đầy danh sách RFQ. NCC được chọn chỉ được
    ghi vào dòng YCMH (actual_*), rồi nút "Tạo RFQ" có sẵn tạo PO thật.

    Sale là người tạo yêu cầu báo giá, có khi trước khi YCMH về Odoo — nên YCMH không
    bắt buộc; gắn YCMH sau thì dòng báo giá tự ghép vào dòng YCMH theo sản phẩm. Thu
    mua chỉ "Chọn" được dòng đã ghép.
    """

    _name = "hlv.vendor.quote"
    _description = "Yêu cầu báo giá nhà cung cấp"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Số báo giá", required=True, readonly=True, copy=False, default="Mới"
    )
    request_id = fields.Many2one(
        "purchase.request",
        string="Yêu cầu mua hàng",
        index=True,
        ondelete="set null",
        tracking=True,
    )
    origin = fields.Char(related="request_id.origin", store=True, string="Tài liệu nguồn")
    opportunity_ref = fields.Char(related="inquiry_id.opportunity_ref", store=True, index=True, string="Số cơ hội")
    sale_order_id = fields.Many2one(
        "sale.order", string="Đơn bán liên quan", index=True, tracking=True
    )
    inquiry_id = fields.Many2one(
        "hlv.vendor.inquiry", string="Phiếu hỏi giá", index=True, ondelete="cascade", readonly=True
    )
    # Không bắt buộc lúc nháp: sale nhập mặt hàng trước rồi mới chọn NCC từ gợi ý.
    partner_id = fields.Many2one("res.partner", string="Nhà cung cấp", index=True, tracking=True)
    access_id = fields.Many2one(
        "hlv.vendor.quote.access",
        string="Link NCC",
        readonly=True,
        index=True,
        ondelete="restrict",
    )
    portal_url = fields.Char(related="access_id.portal_url", string="Link báo giá")
    portal_quote_url = fields.Char(
        string="Link thẳng vào báo giá", compute="_compute_portal_quote_url"
    )
    portal_password = fields.Char(related="access_id.password", string="Mật khẩu")
    user_id = fields.Many2one(
        "res.users", string="Người yêu cầu báo giá", default=lambda self: self.env.user, tracking=True
    )
    company_id = fields.Many2one(
        "res.company", string="Công ty", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    date_deadline = fields.Date(string="Hạn báo giá", tracking=True)
    note = fields.Text(string="Lời nhắn gửi NCC")
    vendor_note = fields.Text(string="Ghi chú của NCC", copy=False)
    submit_date = fields.Datetime(string="NCC gửi lúc", readonly=True, copy=False)
    price_valid_until = fields.Date(
        string="Giá hiệu lực đến", copy=False, tracking=True,
        help="NCC ghi khi báo giá (mặc định 7 ngày). Còn hiệu lực thì phiếu hỏi giá sau — của bất "
             "kỳ sale nào — tự dùng lại giá này, không phải hỏi lại NCC.",
    )
    state = fields.Selection(
        [
            ("draft", "Nháp"),
            ("sent", "Chờ NCC báo giá"),
            ("quoted", "NCC đã báo giá"),
            ("done", "Đã đóng"),
            ("cancel", "Đã huỷ"),
        ],
        string="Trạng thái",
        default="draft",
        required=True,
        copy=False,
        tracking=True,
    )
    line_ids = fields.One2many("hlv.vendor.quote.line", "quote_id", string="Mặt hàng", copy=True)
    amount_untaxed = fields.Monetary(
        string="Tổng chưa VAT", compute="_compute_amounts", store=True, currency_field="currency_id"
    )
    amount_total = fields.Monetary(
        string="Tổng sau VAT", compute="_compute_amounts", store=True, currency_field="currency_id"
    )
    selected_line_count = fields.Integer(
        string="Số dòng được chọn", compute="_compute_selected_line_count"
    )

    @api.depends("line_ids.price_subtotal", "line_ids.price_total")
    def _compute_amounts(self):
        for quote in self:
            quote.amount_untaxed = sum(quote.line_ids.mapped("price_subtotal"))
            quote.amount_total = sum(quote.line_ids.mapped("price_total"))

    @api.depends("access_id.portal_url")
    def _compute_portal_quote_url(self):
        for quote in self:
            quote.portal_quote_url = (
                f"{quote.access_id.portal_url}/{quote.id}" if quote.access_id and quote.id else False
            )

    @api.depends("line_ids.selected")
    def _compute_selected_line_count(self):
        for quote in self:
            quote.selected_line_count = len(quote.line_ids.filtered("selected"))

    @api.constrains("request_id", "partner_id", "state")
    def _check_one_open_quote_per_vendor(self):
        """Hai báo giá mở của cùng NCC cho cùng YCMH làm bảng so sánh đếm trùng NCC."""
        for quote in self.filtered(lambda q: q.request_id and q.access_id and q.state != "cancel"):
            duplicate = self.search_count([
                ("id", "!=", quote.id),
                ("request_id", "=", quote.request_id.id),
                ("access_id", "=", quote.access_id.id),
                ("state", "!=", "cancel"),
            ])
            if duplicate:
                raise ValidationError(_(
                    "%(vendor)s đã có yêu cầu báo giá cho %(request)s. "
                    "Huỷ báo giá cũ trước khi tạo cái mới.",
                    vendor=quote.partner_id.commercial_partner_id.display_name,
                    request=quote.request_id.name,
                ))

    @api.constrains("partner_id", "state")
    def _check_vendor_when_sent(self):
        for quote in self:
            if quote.state != "draft" and not quote.partner_id:
                raise ValidationError(_("%s chưa chọn nhà cung cấp.", quote.name))

    @api.model_create_multi
    def create(self, vals_list):
        Access = self.env["hlv.vendor.quote.access"]
        Partner = self.env["res.partner"]
        for vals in vals_list:
            if vals.get("name", "Mới") == "Mới":
                vals["name"] = self.env["ir.sequence"].next_by_code("hlv.vendor.quote") or "Mới"
            if vals.get("partner_id"):
                vals["access_id"] = Access._get_for_partner(Partner.browse(vals["partner_id"])).id
        quotes = super().create(vals_list)
        quotes.filtered("request_id")._link_request_lines()
        quotes._fill_sale_order_from_request()
        return quotes

    def write(self, vals):
        if vals.get("partner_id"):
            partner = self.env["res.partner"].browse(vals["partner_id"])
            vals["access_id"] = self.env["hlv.vendor.quote.access"]._get_for_partner(partner).id
        if "request_id" in vals:
            changed = self.filtered(lambda q: q.request_id.id != vals["request_id"])
            if changed.line_ids.filtered("selected"):
                raise UserError(_(
                    "Thu mua đã chọn giá trong báo giá này. Bỏ chọn trước rồi mới đổi YCMH."
                ))
        result = super().write(vals)
        if "request_id" in vals or "line_ids" in vals:
            self._link_request_lines()
        if "request_id" in vals:
            self._fill_sale_order_from_request()
        return result

    def _fill_sale_order_from_request(self):
        """Đơn bán lấy theo YCMH khi báo giá chưa có. Trang sale tạo báo giá không qua
        onchange, nên không làm ở đây thì báo giá không tìm được theo đơn bán / mã sale."""
        for quote in self.filtered(lambda q: not q.sale_order_id and q.request_id.sale_order_id):
            quote.sale_order_id = quote.request_id.sale_order_id

    @api.onchange("request_id")
    def _onchange_request_id(self):
        if not self.request_id:
            return
        if self.request_id.sale_order_id:
            self.sale_order_id = self.request_id.sale_order_id
        self.company_id = self.request_id.company_id or self.company_id
        if not self.line_ids:
            lines = self._quotable_request_lines(self.request_id)
            self.line_ids = [Command.create(vals) for vals in self._line_vals_from_request_lines(lines)]

    def _link_request_lines(self):
        """Ghép dòng báo giá chưa gắn vào dòng YCMH cùng sản phẩm; gỡ dòng gắn nhầm YCMH khác.

        Dòng sale nhập tay trước khi có YCMH không biết dòng YCMH nào; không ghép thì
        thu mua không "Chọn" được và giá không chảy vào nút Tạo RFQ.
        """
        for quote in self:
            lines = quote.line_ids
            stale = lines.filtered(
                lambda l: l.request_line_id and l.request_line_id.request_id != quote.request_id
            )
            if stale:
                stale.write({"request_line_id": False})
            if not quote.request_id:
                continue
            unlinked = lines.filtered(lambda l: not l.request_line_id)
            taken = lines.request_line_id
            candidates = self._quotable_request_lines(quote.request_id) - taken
            matched = match_by_product(
                [(line.id, line.product_id.id) for line in unlinked],
                [(line.id, line.product_id.id) for line in candidates],
            )
            for line in unlinked:
                if line.id in matched:
                    line.request_line_id = matched[line.id]

    # purchased_qty của dòng YCMH không lưu và tính từ dòng PO — sale không có quyền đọc PO.
    # Hai hàm dưới chỉ đọc "đã lên PO bao nhiêu" bằng sudo, thay vì cấp cho sale quyền
    # đọc toàn bộ dòng đơn mua.
    @api.model
    def _quotable_request_lines(self, request):
        """Dòng YCMH còn cần mua: chưa huỷ, không đánh dấu bỏ qua, chưa lên đủ PO."""
        lines = request.sudo().line_ids.filtered(
            lambda l: not l.cancelled
            and not l.skip_processing
            and l.purchased_qty < l.product_qty
        )
        return request.line_ids.browse(lines.ids)

    @api.model
    def _line_vals_from_request_lines(self, request_lines):
        """Giá trị dòng báo giá — số lượng là phần còn chưa lên PO, khớp với wizard Tạo RFQ."""
        return [
            {
                "sequence": index,
                "request_line_id": line.id,
                "product_id": line.product_id.id,
                "name": line.name or line.product_id.display_name,
                "product_qty": line.product_qty - line.purchased_qty,
                "product_uom_id": line.product_uom_id.id,
            }
            for index, line in enumerate(request_lines.sudo(), start=1)
        ]

    @api.model
    def _vendors_with_open_quote(self, request):
        """Công ty NCC đã có báo giá chưa huỷ cho YCMH này. Không có YCMH → rỗng."""
        if not request:
            return self.env["res.partner"]
        return request.vendor_quote_ids.filtered(lambda q: q.state != "cancel").access_id.partner_id

    @api.model
    def _create_and_send(self, vendors, line_vals, request=None, date_deadline=False, note=False):
        """Gửi danh sách mặt hàng cho các NCC, mở ngay cho NCC báo giá.

        Dùng chung cho wizard backend và trang /hoi-gia-ncc của sale. Mỗi YCMH, mỗi NCC chỉ
        một báo giá (bảng so sánh đếm theo NCC), nên NCC đã có báo giá đang mở cho YCMH này
        thì hàng được BỔ SUNG vào báo giá đó (xem _merge_lines) thay vì tạo báo giá thứ hai.
        NCC có báo giá đã đóng cho YCMH này thì bỏ qua.
        """
        if not line_vals:
            raise UserError(_("Chọn ít nhất một mặt hàng cần báo giá."))
        open_quotes = {}
        if request:
            for quote in request.vendor_quote_ids.filtered(lambda q: q.state in ("draft", "sent", "quoted")):
                open_quotes[quote.access_id.partner_id.id] = quote
        closed_vendors = self._vendors_with_open_quote(request) - self.env["res.partner"].browse(list(open_quotes))

        updated = self.browse()
        new_vendors = self.env["res.partner"]
        for vendor in vendors.commercial_partner_id:
            if vendor.id in open_quotes:
                quote = open_quotes[vendor.id]
                quote._merge_lines(line_vals, date_deadline, note)
                updated |= quote
            elif vendor not in closed_vendors:
                new_vendors |= vendor
        if not updated and not new_vendors:
            raise UserError(_(
                "Các NCC đã chọn đều có báo giá đã đóng cho YCMH này — mở lại báo giá đó nếu cần hỏi thêm."
            ))
        created = self.create([
            {
                "request_id": request.id if request else False,
                "partner_id": vendor.id,
                "date_deadline": date_deadline,
                "note": note,
                "state": "sent",
                "line_ids": [Command.create(vals) for vals in line_vals],
            }
            for vendor in new_vendors
        ])
        return updated | created

    def _merge_lines(self, line_vals, date_deadline=False, note=False):
        """Bổ sung mặt hàng vào báo giá đang mở của cùng YCMH.

        Dòng ứng với cùng dòng YCMH lấy số lượng mới (YCMH vừa được gộp thêm); dòng mới thêm
        vào cuối. Giá NCC đã điền giữ nguyên. Có thay đổi thì báo giá về "Chờ NCC báo giá"
        để NCC báo nốt phần mới — trang NCC bắt điền đủ giá mới cho gửi lại.
        """
        self.ensure_one()
        changed = False
        next_sequence = max(self.line_ids.mapped("sequence") or [0]) + 1
        for vals in line_vals:
            request_line_id = vals.get("request_line_id")
            line = self.line_ids.filtered(
                lambda l: request_line_id and l.request_line_id.id == request_line_id
            )[:1]
            if line:
                if line.product_qty != vals["product_qty"]:
                    line.product_qty = vals["product_qty"]
                    changed = True
            else:
                self.env["hlv.vendor.quote.line"].create(
                    dict(vals, quote_id=self.id, sequence=next_sequence)
                )
                next_sequence += 1
                changed = True
        updates = {}
        if date_deadline and (not self.date_deadline or date_deadline > self.date_deadline):
            updates["date_deadline"] = date_deadline
        if note:
            updates["note"] = note
        if changed and self.state in ("draft", "quoted"):
            updates["state"] = "sent"
        if updates:
            self.write(updates)
        if changed:
            self.message_post(body=_("Bổ sung / cập nhật mặt hàng — NCC cần báo giá phần mới."))
        return changed

    # ------------------------------------------------------------------
    # Nút thao tác nội bộ
    # ------------------------------------------------------------------
    def action_send(self):
        for quote in self:
            if not quote.line_ids:
                raise UserError(_("%s chưa có mặt hàng nào.", quote.name))
            if not quote.partner_id:
                raise UserError(_(
                    "%s chưa chọn nhà cung cấp — bấm \"Gợi ý & gửi NCC\" để chọn.", quote.name
                ))
        self.write({"state": "sent"})

    def action_open_vendor_wizard(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Thêm mặt hàng trước để hệ thống gợi ý nhà cung cấp."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Gợi ý & gửi nhà cung cấp"),
            "res_model": "hlv.vendor.quote.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_source_quote_id": self.id},
        }

    def action_close(self):
        self.write({"state": "done"})

    def action_reopen(self):
        self.write({"state": "sent"})

    def action_cancel(self):
        selected = self.line_ids.filtered("selected")
        if selected:
            selected.action_unselect()
        self.write({"state": "cancel"})

    def action_draft(self):
        self.write({"state": "draft"})

    def action_open_compare(self):
        if not self.request_id:
            raise UserError(_("Gắn Yêu cầu mua hàng cho báo giá này trước rồi mới so sánh."))
        return self.request_id.action_compare_vendor_quotes()

    # ------------------------------------------------------------------
    # Phía NCC (gọi từ controller công khai bằng sudo)
    # ------------------------------------------------------------------
    @api.model
    def _vendor_today(self):
        # Hạn báo giá tính hết ngày theo giờ VN; NCC không có múi giờ trong Odoo.
        tz = pytz.timezone(DEFAULT_TZ)
        return fields.Datetime.now().replace(tzinfo=pytz.utc).astimezone(tz).date()

    @api.model
    def _vendor_status_domain(self, status):
        """Domain của một trạng thái NCC thấy — nơi duy nhất định nghĩa các trạng thái đó.

        Dùng cho cả tab lọc (search) lẫn nhãn từng báo giá (filtered_domain), để hai chỗ
        không lệch nhau khi đổi quy tắc hạn.
        """
        today = self._vendor_today()
        not_overdue = ["|", ("date_deadline", "=", False), ("date_deadline", ">=", today)]
        return {
            "waiting": [("state", "=", "sent")] + not_overdue,
            "quoted": [("state", "=", "quoted")] + not_overdue,
            "expired": [("state", "in", ("sent", "quoted")), ("date_deadline", "<", today)],
            "closed": [("state", "=", "done")],
        }[status]

    def _vendor_status(self):
        self.ensure_one()
        for status in VENDOR_STATUSES:
            if self.filtered_domain(self._vendor_status_domain(status)):
                return status
        return False

    def _is_open_for_vendor(self):
        """NCC còn sửa được: đang chờ/đã báo giá, chưa qua hết ngày hạn (giờ VN), và còn ít
        nhất một mặt hàng chưa lên đơn mua."""
        self.ensure_one()
        return self._vendor_status() in VENDOR_EDITABLE_STATUSES and not self._fully_ordered()

    def _fully_reused(self):
        """Mọi dòng đều lấy giá còn hiệu lực từ báo giá trước (services/price_reuse.py) — coi như
        NCC đã báo, không cần gửi link. Xét TỪNG dòng: mapped() trên field quan hệ trả recordset
        đã gộp, báo giá không dòng nào kế thừa thì rỗng — all() của rỗng lại là True."""
        self.ensure_one()
        return bool(self.line_ids) and all(line.inherited_from_id for line in self.line_ids)

    def _fully_ordered(self):
        """Mọi mặt hàng đều đã lên đơn mua — báo giá khoá hẳn với NCC."""
        self.ensure_one()
        return bool(self.line_ids) and all(self.line_ids.mapped("vendor_locked"))

    def _vendor_submit(self, line_values, vendor_note, price_valid_until=False):
        """Ghi báo giá NCC gửi lên.

        line_values: {quote_line_id: {"price_unit", "list_price", "discount", "vat",
        "delivery_days", "vendor_note", "invoice_name", "unavailable"}} — controller đã đọc số xong.
        Mọi dòng phải khai: có giá + VAT, hoặc NCC bấm "×" (unavailable = không có hàng — sale không
        chọn được). Dòng đã lên đơn mua (vendor_locked) giữ nguyên — giá trị gửi lên cho dòng đó bị bỏ qua.
        price_valid_until: date NCC ghi; trống → hôm nay + 7 ngày. Trước hôm nay → UserError.
        """
        self.ensure_one()
        if not self._is_open_for_vendor():
            raise UserError(_("Báo giá này đã đóng, đã quá hạn hoặc đã lên đơn mua hết — không sửa được nữa."))

        open_lines = self.line_ids.filtered(lambda l: not l.vendor_locked)
        submitted = {line.id: line_values.get(line.id, {}) for line in open_lines}
        missing = [
            str(index) for index, line in enumerate(self.line_ids, start=1)
            if line.id in submitted and not submitted[line.id].get("unavailable")
            and not (submitted[line.id].get("price_unit") and submitted[line.id].get("vat"))
        ]
        if missing:
            raise UserError(_(
                "Dòng %s chưa có đơn giá hoặc VAT. Mặt hàng không có thì bấm \"×\" cạnh mã hàng.",
                ", ".join(missing),
            ))

        chosen_before = {
            line.id: (line.price_unit, line.unavailable) for line in self.line_ids.filtered("selected")
        }
        for line in open_lines:
            vals = dict(submitted[line.id])
            if vals.get("unavailable"):
                vals.update(price_unit=0.0, list_price=0.0, discount=0.0, vat=False)
            line.write(vals)
        self._notify_chosen_lines_changed(chosen_before)
        resubmitted = self.state == "quoted"
        today = self._vendor_today()
        if price_valid_until and price_valid_until < today:
            raise UserError(_("Ngày giá hiệu lực đến không được trước hôm nay."))
        self.write({
            "vendor_note": vendor_note,
            "state": "quoted",
            "submit_date": fields.Datetime.now(),
            "price_valid_until": price_valid_until or default_price_valid_until(today),
        })
        self._notify_vendor_submitted(resubmitted)

    def _vendor_purchase_orders(self):
        """Đơn mua (đã xác nhận) của chính NCC này cho các mặt hàng của báo giá: dòng báo giá →
        dòng YCMH → dòng đơn mua của NCC này. Không chỉ dòng đang được chọn — NCC giao thiếu
        rồi sale chọn NCC khác cho phần còn lại thì NCC cũ vẫn thấy đơn của mình (cùng luật với
        purchase.order._compute_hlv_vendor_links). Đọc bằng sudo — gọi được từ trang NCC.
        Gồm cả đơn đã xác nhận rồi bị hủy (còn date_approve) — NCC cần biết để khỏi giao; đơn hủy
        từ lúc còn nháp thì NCC chưa từng thấy, không hiện."""
        orders = self.env["purchase.order"]
        for quote in self.sudo():
            request_lines = quote.line_ids.inquiry_line_id.request_line_id | quote.line_ids.request_line_id
            orders |= request_lines.purchase_lines.order_id.filtered(
                lambda o, v=quote.access_id.partner_id: (
                    o.state in ("purchase", "done") or (o.state == "cancel" and o.date_approve)
                ) and o.partner_id.commercial_partner_id == v
            )
        return orders

    def _chat_contacts(self):
        """Người trong công ty cần biết khi NCC nhắn trên báo giá: người hỏi giá + sale tạo phiếu."""
        self.ensure_one()
        return (self.user_id | self.inquiry_id.user_id).partner_id

    def _notify_chosen_lines_changed(self, chosen_before):
        """NCC sửa giá / báo hết hàng cho mặt hàng sale đã chọn (có khi đã lên YCMH) — báo lên
        phiếu và YCMH để sale chọn lại. Không tự đổi giá trên YCMH: giá mua phải do người quyết."""
        changes = []
        for line in self.line_ids.filtered(lambda l: l.id in chosen_before):
            old_price, old_unavailable = chosen_before[line.id]
            if line.unavailable and not old_unavailable:
                changes.append((line, _("báo HẾT HÀNG")))
            elif line.price_unit != old_price:
                changes.append((line, _("đổi giá %(old)s → %(new)s", old=self.currency_id.format(old_price),
                                         new=self.currency_id.format(line.price_unit))))
        if not changes:
            return
        items = Markup("").join(
            Markup("<li>%s: %s</li>") % (line.name or line.product_id.display_name, text) for line, text in changes
        )
        body = Markup("<p>%s</p><ul>%s</ul>") % (
            _("%s sửa báo giá cho mặt hàng đang được chọn — kiểm tra và chọn lại NCC nếu cần:",
              self.partner_id.commercial_partner_id.display_name),
            items,
        )
        requests = self.line_ids.filtered(lambda l: l.id in chosen_before).request_line_id.request_id
        for record in list(self.inquiry_id) + list(requests):
            post_internal(record, body, self.partner_id)

    def _notify_vendor_submitted(self, resubmitted):
        offered = self.line_ids.filtered(lambda l: not l.unavailable)
        body = Markup("<p>%s</p><p>%s</p>") % (
            _("NCC đã cập nhật báo giá.") if resubmitted else _("NCC đã gửi báo giá."),
            _(
                "Báo %(offered)s/%(total)s mặt hàng — tổng chưa VAT %(amount)s.",
                offered=len(offered),
                total=len(self.line_ids),
                amount=self.currency_id.format(self.amount_untaxed),
            ),
        )
        # Ghi chú nội bộ gọi tên follower nội bộ (sale tạo phiếu, thu mua theo dõi YCMH) — không
        # email cho NCC / đối tác bên ngoài (xem services/notify.py).
        post_internal(self, body, self.partner_id)
        headline = Markup("<p>%s</p>%s") % (
            _("%(vendor)s đã báo giá %(quote)s.", vendor=self.partner_id.display_name, quote=self.name),
            body,
        )
        for record in list(self.inquiry_id) + list(self.request_id):
            post_internal(record, headline, self.partner_id)
        # Trang /hoi-gia-ncc đang mở: chuông + popup + tiếng cho sale (gửi sau khi commit).
        notify_quoted(self, resubmitted)
