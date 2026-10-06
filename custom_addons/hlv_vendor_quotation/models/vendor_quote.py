# -*- coding: utf-8 -*-
import pytz

from markupsafe import Markup
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .vendor_quote_utils import match_by_product

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
    sale_order_id = fields.Many2one(
        "sale.order", string="Đơn bán liên quan", index=True, tracking=True
    )
    partner_id = fields.Many2one(
        "res.partner", string="Nhà cung cấp", required=True, index=True, tracking=True
    )
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
    vendor_note = fields.Text(string="Ghi chú của NCC")
    submit_date = fields.Datetime(string="NCC gửi lúc", readonly=True, copy=False)
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
        for quote in self.filtered(lambda q: q.request_id and q.state != "cancel"):
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
        return result

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

    # ------------------------------------------------------------------
    # Nút thao tác nội bộ
    # ------------------------------------------------------------------
    def action_send(self):
        for quote in self:
            if not quote.line_ids:
                raise UserError(_("%s chưa có mặt hàng nào.", quote.name))
        self.write({"state": "sent"})

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
        """NCC còn sửa được: đang chờ/đã báo giá và chưa qua hết ngày hạn (giờ VN)."""
        self.ensure_one()
        return self._vendor_status() in VENDOR_EDITABLE_STATUSES

    def _vendor_submit(self, line_values, vendor_note):
        """Ghi báo giá NCC gửi lên.

        line_values: {quote_line_id: {"price_unit", "vat", "delivery_days",
        "vendor_note", "unavailable"}} — controller đã đọc số xong.
        Mọi dòng phải có giá + VAT, trừ dòng NCC đánh dấu không cung cấp.
        """
        self.ensure_one()
        if not self._is_open_for_vendor():
            raise UserError(_("Báo giá này đã đóng hoặc đã quá hạn, không sửa được nữa."))

        missing = []
        for index, line in enumerate(self.line_ids, start=1):
            vals = line_values.get(line.id, {})
            if not vals.get("unavailable") and (not vals.get("price_unit") or not vals.get("vat")):
                missing.append(str(index))
        if missing:
            raise UserError(_(
                "Dòng %s chưa có đơn giá hoặc VAT. Mặt hàng nào không cung cấp được, "
                "hãy tích \"Không có hàng\".",
                ", ".join(missing),
            ))

        for line in self.line_ids:
            vals = dict(line_values[line.id])
            if vals.get("unavailable"):
                vals.update(price_unit=0.0, vat=False)
            line.write(vals)
        resubmitted = self.state == "quoted"
        self.write({
            "vendor_note": vendor_note,
            "state": "quoted",
            "submit_date": fields.Datetime.now(),
        })
        self._notify_vendor_submitted(resubmitted)

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
        # mt_comment để follower nhận thông báo: sale tạo báo giá theo dõi báo giá,
        # thu mua theo dõi YCMH — cả hai cần biết NCC đã báo giá.
        self.message_post(
            body=body,
            author_id=self.partner_id.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        if self.request_id:
            self.request_id.message_post(
                body=Markup("<p>%s</p>%s") % (
                    _("%(vendor)s đã báo giá %(quote)s.", vendor=self.partner_id.display_name, quote=self.name),
                    body,
                ),
                author_id=self.partner_id.id,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
