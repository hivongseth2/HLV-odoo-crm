# -*- coding: utf-8 -*-
"""Thu mua đề xuất đổi một dòng đơn mua lên từ hỏi giá (giá, và tuỳ chọn SL / mã — po_proposal_change.py) — thay cho
việc sửa tay ở backend.

Luồng: thu mua ghi giá gợi ý / SL / mã (đều tuỳ chọn) + lý do → trang /hoi-gia-ncc của sale hiện việc cần làm → sale sửa
lại nếu cần rồi gửi: hỏi lại NCC (món mở lại trên báo giá của chính NCC của đơn — vendor_quote_requote.py, NCC báo trên
trang NCC → sale "Gửi thu mua duyệt"), hoặc không cần NCC báo giá (VD chỉ giảm SL) thì gửi thẳng thu mua duyệt. Thu mua
duyệt thì đơn đổi, ghi thành một phiên bản của đơn (hlv.po.revision, có bản chụp trước / sau như yêu cầu của NCC) —
lịch sử từng dòng xem ở cột "Lịch sử" trên đơn mua. Sale cũng báo được "NCC giữ giá" để đóng đề xuất.
"""

from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.notify import post_internal
from ..services.vendor_chat import post_chat
from .price_proposal_utils import money_text, requote_message, same_money, vat_label, vat_note, vat_rate
from .purchase_order_revision import tax_rate_of
from .vendor_quote_utils import format_vn_number, price_incl_vat

PROPOSAL_STATES = [
    ("sale", "Chờ sale hỏi lại NCC"),
    ("vendor", "Chờ NCC báo lại giá"),
    ("quoted", "NCC đã báo lại — chờ sale gửi duyệt"),
    ("to_approve", "Chờ thu mua duyệt"),
    ("rejected", "Thu mua không duyệt — sale hỏi lại"),
    ("approved", "Đã duyệt — đã đổi đơn"),
    ("kept", "NCC giữ giá cũ"),
    ("cancel", "Thu mua đã huỷ"),
]
# Đề xuất chưa xong: mỗi dòng đơn mua chỉ một cái. "rejected" vẫn mở — sale hỏi lại NCC lần nữa hoặc báo giữ giá.
OPEN_STATES = ("sale", "vendor", "quoted", "to_approve", "rejected")
REQUOTE_FROM = ("sale", "quoted", "rejected")
# Đề xuất đang chờ SALE làm (hỏi lại NCC / gửi thu mua duyệt) — bộ lọc "Thu mua trả về giá" trên trang hỏi giá.
SALE_TODO_STATES = ("sale", "quoted", "rejected")
KEEP_FROM = ("sale", "vendor", "quoted", "rejected")


class PurchaseOrderPriceProposal(models.Model):
    _name = "hlv.po.price.proposal"
    _description = "Thu mua đề xuất giá dòng đơn mua"
    _order = "id desc"

    name = fields.Char(string="Đề xuất", compute="_compute_name")
    purchase_order_id = fields.Many2one("purchase.order", string="Đơn mua", required=True, index=True,
                                        ondelete="cascade", readonly=True)
    order_line_id = fields.Many2one("purchase.order.line", string="Dòng đơn mua", required=True, index=True,
                                    ondelete="cascade", readonly=True)
    product_id = fields.Many2one(related="order_line_id.product_id", string="Sản phẩm")
    partner_id = fields.Many2one(related="purchase_order_id.partner_id", string="Nhà cung cấp")
    # Dòng báo giá của chính NCC của đơn cho món này — chỗ NCC báo lại giá trên trang NCC.
    quote_line_id = fields.Many2one("hlv.vendor.quote.line", string="Dòng báo giá NCC", readonly=True,
                                    ondelete="set null")
    inquiry_id = fields.Many2one("hlv.vendor.inquiry", string="Phiếu hỏi giá", index=True, readonly=True,
                                 ondelete="set null")
    state = fields.Selection(PROPOSAL_STATES, string="Trạng thái", default="sale", required=True, readonly=True)
    tax_rate = fields.Float(string="% VAT trên đơn", readonly=True)
    old_price_incl = fields.Float(string="Giá trên đơn (sau VAT)", digits="Product Price", readonly=True)
    suggested_price_incl = fields.Float(string="Giá thu mua gợi ý (sau VAT)", digits="Product Price", readonly=True)
    buyer_note = fields.Text(string="Lý do của thu mua", readonly=True)
    buyer_id = fields.Many2one("res.users", string="Thu mua đề xuất", readonly=True,
                               default=lambda self: self.env.user)
    vendor_message = fields.Text(string="Tin sale gửi NCC", readonly=True)
    sale_user_id = fields.Many2one("res.users", string="Sale hỏi lại", readonly=True)
    requote_date = fields.Datetime(string="Hỏi lại NCC lúc", readonly=True)
    vendor_price_incl = fields.Float(string="NCC báo lại (sau VAT)", digits="Product Price", readonly=True)
    vendor_tax_rate = fields.Float(string="% VAT NCC báo", readonly=True)
    vendor_date = fields.Datetime(string="NCC báo lại lúc", readonly=True)
    new_price_incl = fields.Float(string="Giá gửi duyệt (sau VAT)", digits="Product Price", readonly=True)
    sale_note = fields.Char(string="Ghi chú của sale", readonly=True)
    submit_date = fields.Datetime(string="Gửi duyệt lúc", readonly=True)
    decided_user_id = fields.Many2one("res.users", string="Người duyệt", readonly=True)
    decided_date = fields.Datetime(string="Duyệt lúc", readonly=True)
    reject_reason = fields.Char(string="Lý do không duyệt")
    revision_id = fields.Many2one("hlv.po.revision", string="Phiên bản đơn đã áp", readonly=True, ondelete="set null")
    activity_id = fields.Many2one("mail.activity", string="Hoạt động", readonly=True, ondelete="set null")
    vat_warning = fields.Char(string="Lưu ý VAT", compute="_compute_vat_warning")
    vendor_kept_price = fields.Boolean(
        string="NCC giữ nguyên giá", compute="_compute_vendor_kept_price",
        help="NCC đã gửi lại báo giá nhưng giá sau VAT không đổi so với giá trên đơn — không có gì để thu mua duyệt.",
    )

    @api.depends("vendor_date", "vendor_price_incl", "old_price_incl", "new_qty", "new_drop", "new_product_id",
                 "new_vat")
    def _compute_vendor_kept_price(self):
        # Đổi SL / mã thì giá bằng giá cũ vẫn là thay đổi cần duyệt — không phải "giữ giá".
        for proposal in self:
            proposal.vendor_kept_price = bool(proposal.vendor_date) and not proposal._has_line_change() and same_money(
                proposal.vendor_price_incl, proposal.old_price_incl)

    @api.depends("purchase_order_id.name", "product_id")
    def _compute_name(self):
        for proposal in self:
            proposal.name = f"{proposal.purchase_order_id.name} · {proposal.product_id.display_name or ''}"

    @api.depends("tax_rate", "vendor_tax_rate", "vendor_date")
    def _compute_vat_warning(self):
        for proposal in self:
            proposal.vat_warning = vat_note(proposal.tax_rate, proposal.vendor_tax_rate) if proposal.vendor_date else ""

    @api.model
    def _sale_todo_inquiry_ids(self):
        """Id các phiếu hỏi giá có đề xuất giá đang chờ sale làm (SALE_TODO_STATES). Đọc bằng sudo — sale không có quyền
        model này; nơi gọi tự lọc phiếu theo phạm vi mã sale."""
        groups = self.sudo()._read_group([("state", "in", SALE_TODO_STATES), ("inquiry_id", "!=", False)], ["inquiry_id"])
        return [inquiry.id for (inquiry,) in groups]

    # ------------------------------------------------------------------ thu mua đề xuất
    @api.model
    def _quote_line_of(self, po_line):
        """Dòng báo giá của NCC của đơn cho món của dòng đơn mua (qua dòng YCMH), ưu tiên dòng đang được chọn, mới
        nhất. Không có (đơn không đi từ phiếu hỏi giá) → recordset rỗng."""
        request_lines = po_line.sudo().purchase_request_lines
        if not request_lines:
            return self.env["hlv.vendor.quote.line"]
        vendor = po_line.order_id.partner_id.commercial_partner_id
        lines = self.env["hlv.vendor.quote.line"].sudo().search([
            ("inquiry_line_id", "!=", False), ("quote_id.state", "!=", "cancel"),
            ("quote_id.partner_id.commercial_partner_id", "=", vendor.id),
            "|", "|", ("request_line_id", "in", request_lines.ids),
            ("backorder_request_line_id", "in", request_lines.ids),
            ("inquiry_line_id.request_line_ids", "in", request_lines.ids),
        ])
        return lines.sorted(lambda l: (not l.selected, -l.id))[:1]

    @api.model
    def _check_can_propose(self, po_line):
        """Lỗi (UserError) khi dòng không đề xuất giá được; trả dòng báo giá NCC sẽ hỏi lại."""
        if not po_line.hlv_price_locked:
            raise UserError(_("Dòng này không gắn với phiếu hỏi giá — giá sửa trực tiếp trên đơn như bình thường."))
        if po_line.order_id.state == "cancel":
            raise UserError(_("Đơn %s đã huỷ.", po_line.order_id.name))
        if po_line.qty_invoiced:
            raise UserError(_("%s đã có hoá đơn NCC — không đổi giá trên đơn được nữa.", po_line.product_id.display_name))
        open_one = self.search([("order_line_id", "=", po_line.id), ("state", "in", OPEN_STATES)], limit=1)
        if open_one:
            raise UserError(_("%(product)s đang có đề xuất giá (%(state)s) — xử lý xong cái đó trước.",
                              product=po_line.product_id.display_name,
                              state=dict(PROPOSAL_STATES)[open_one.state]))
        quote_line = self._quote_line_of(po_line)
        if not quote_line:
            raise UserError(_("Không tìm thấy báo giá của %s cho món này trên trang hỏi giá — không hỏi lại NCC được.",
                              po_line.order_id.partner_id.commercial_partner_id.display_name))
        return quote_line

    @api.model
    def _buyer_propose(self, po_line, suggested_incl, note, qty=None, product=None, vat=""):
        """Thu mua gửi đề xuất: giá gợi ý (sau VAT, 0 / bằng giá trên đơn = không gợi ý), SL mới (None / bằng SL trên đơn
        = giữ, 0 = không mua nữa), mã thay thế (rỗng = giữ), mã VAT (rỗng / bằng VAT trên đơn = giữ) + lý do (bắt buộc —
        có thể chỉ có lý do). Trả đề xuất vừa tạo; báo sale trên trang hỏi giá."""
        quote_line = self._check_can_propose(po_line)
        if suggested_incl < 0 or (qty or 0.0) < 0:
            raise UserError(_("Giá gợi ý / số lượng không được âm."))
        drop = qty is not None and qty <= 1e-6
        note = (note or "").strip()
        if not note:
            raise UserError(_("Ghi lý do để sale biết cần hỏi lại NCC điều gì (VD giá thị trường, mua thêm, đổi mã)."))
        if product == po_line.product_id:
            product = None
        if drop and product:
            raise UserError(_("Không mua nữa thì không đổi mã — đổi mã thì ghi SL mua mã mới."))
        tax = tax_rate_of(po_line)
        old_incl = price_incl_vat(po_line.price_unit, tax)
        if same_money(suggested_incl, old_incl):
            suggested_incl = 0.0
        proposal = self.sudo().create({
            "purchase_order_id": po_line.order_id.id, "order_line_id": po_line.id, "quote_line_id": quote_line.id,
            "inquiry_id": quote_line.inquiry_line_id.inquiry_id.id, "tax_rate": tax,
            "old_price_incl": old_incl, "suggested_price_incl": suggested_incl,
            "buyer_note": note, "buyer_id": self.env.uid, "old_qty": po_line.product_qty,
            "suggested_qty": qty if qty and not drop and abs(qty - po_line.product_qty) > 1e-6 else 0.0,
            "suggested_drop": drop,
            "suggested_product_id": product.id if product else False,
            "suggested_vat": vat if vat and abs(vat_rate(vat) - tax) > 1e-6 else False,
        })
        texts = dict(proposal._texts(), wish=proposal._buyer_wish_text())
        proposal._post_order(Markup(_("Thu mua <b>trả về</b> %(product)s (%(wish)s). Lý do: %(note)s. Chờ sale xử lý."))
                             % texts)
        proposal._post_inquiry(Markup(_("Thu mua trả về <i>%(product)s</i> trên đơn %(order)s (%(wish)s). Lý do: "
                                        "%(note)s — vào trang Hỏi giá NCC xử lý.")) % texts)
        proposal._tell_sale(_("Thu mua trả về %(product)s (%(wish)s) — sale xử lý", **texts))
        return proposal

    # ------------------------------------------------------------------ sale (trang /hoi-gia-ncc)
    def _sale_send(self, qty, product, needs_vendor, price_incl, note, vat=""):
        """Sale chốt SL / mã (sửa lại đề xuất của thu mua nếu cần) rồi gửi:
        - needs_vendor: mở món (hoặc mã mới) trên báo giá của NCC của đơn cho SL mới + nhắn NCC (lời nhắn soạn sẵn theo
          mã / SL / giá mong muốn price_incl, cộng note của sale);
        - không: gửi thẳng thu mua duyệt, giữ giá chưa VAT trên đơn (đổi VAT thì giá sau VAT đổi theo; note là ghi chú
          cho thu mua). Đổi mã luôn phải hỏi NCC (mã mới chưa có giá); không đổi SL / mã / VAT thì cũng phải hỏi NCC
          (không có gì để duyệt). vat: mã VAT muốn đổi (rỗng = giữ)."""
        self.ensure_one()
        self._check_state(REQUOTE_FROM, _("gửi"))
        self._set_line_target(qty, product, vat)
        note = (note or "").strip()
        # Không mua nữa: không có gì cho NCC báo giá — gửi thẳng thu mua (NCC được báo khi duyệt).
        if (not needs_vendor or self.new_drop) and not self._product_changed():
            if not self._has_line_change():
                raise UserError(_("Không đổi số lượng / mã / VAT thì phải hỏi NCC giá mới (hoặc bấm \"NCC giữ giá\")."))
            self._close_requote()
            self.sudo().write({"needs_vendor": False, "vendor_price_incl": 0.0, "vendor_date": False})
            new_incl = self.old_price_incl
            if self._vat_changed():
                unit = self.order_line_id.sudo().price_unit
                new_incl = price_incl_vat(unit, vat_rate(self.new_vat))
            self._submit(new_incl, note, self.new_vat)
            return
        quote_line = self._prepare_target_quote_line()
        if not quote_line:
            raise UserError(_("Không còn dòng báo giá của NCC cho món này."))
        message = self._vendor_request_text(price_incl, note)
        self.sudo().write({"state": "vendor", "needs_vendor": True, "vendor_message": message,
                           "sale_user_id": self.env.uid, "requote_date": fields.Datetime.now(),
                           "vendor_price_incl": 0.0, "vendor_tax_rate": 0.0, "vendor_date": False})
        quote_line.quote_id._hlv_open_requote(quote_line, self, self._target_qty(), self.new_vat)
        post_chat(quote_line.quote_id, message, self.env.user.partner_id, from_vendor=False,
                  sale_code=self.inquiry_id.sale_code or "")
        self._post_order(Markup(_("Sale (%(user)s) đã hỏi lại NCC %(product)s%(change)s.")) % dict(
            self._texts(), user=self.env.user.name))

    def _vendor_request_text(self, price_incl, note):
        """Tin gửi NCC: soạn sẵn theo mã / SL sẽ mua / giá mong muốn, cộng lời của sale."""
        product = self._target_product()
        qty_text = ""
        if self._has_line_change():
            qty_text = f"{format_vn_number(self._target_qty())} {self.uom_id.name or ''}".rstrip()
        replaces = self.product_id.display_name if self._product_changed() else ""
        text = requote_message(product.display_name, price_incl, qty_text, replaces, self.new_vat or "")
        return f"{text} {note}" if note else text

    def _vendor_answered(self, quote_line):
        """NCC vừa gửi lại báo giá có món đang hỏi lại: ghi giá NCC báo, báo sale gửi thu mua duyệt."""
        for proposal in self.sudo().filtered(lambda p: p.state == "vendor"):
            if quote_line.unavailable:
                proposal.write({"state": "quoted", "vendor_price_incl": 0.0, "vendor_date": fields.Datetime.now()})
                proposal._post_inquiry(Markup(_("NCC báo <b>không có hàng</b> <i>%s</i> — đổi mã khác, hỏi lại NCC hoặc "
                                                "bấm \"NCC giữ giá\".")) % quote_line.product_id.display_name,
                                       quote_line.quote_id.partner_id)
                proposal._tell_sale(_("NCC không có hàng %s", quote_line.product_id.display_name), source="vendor")
                continue
            proposal.write({
                "state": "quoted", "vendor_price_incl": price_incl_vat(quote_line.price_unit, quote_line.tax_rate),
                "vendor_tax_rate": quote_line.tax_rate, "vendor_date": fields.Datetime.now(),
            })
            if proposal.vendor_kept_price:
                # NCC bấm gửi lại mà không đổi giá — nói rõ, đừng để sale tưởng có giá mới mà gửi thu mua duyệt.
                proposal._post_inquiry(Markup(_("NCC gửi lại báo giá <i>%(product)s</i> (đơn %(order)s) nhưng <b>giữ nguyên "
                                                "giá</b> %(vendor)s sau VAT — sale thương lượng thêm (hỏi lại NCC) hoặc "
                                                "bấm \"NCC giữ giá\".")) % proposal._texts(),
                                       quote_line.quote_id.partner_id)
                proposal._tell_sale(_("NCC giữ nguyên giá %(product)s (%(vendor)s) — hỏi lại NCC hoặc báo NCC giữ giá",
                                      **proposal._texts()), source="vendor")
                continue
            proposal._post_inquiry(Markup(_("NCC báo lại giá <i>%(product)s</i> (đơn %(order)s): %(vendor)s sau VAT — "
                                            "sale bấm \"Gửi thu mua duyệt\".")) % proposal._texts(),
                                   quote_line.quote_id.partner_id)
            proposal._tell_sale(_("NCC báo lại giá %(product)s: %(vendor)s — sale gửi thu mua duyệt", **proposal._texts()),
                                source="vendor")

    def _sale_submit(self, note):
        """Sale gửi giá NCC vừa báo lại cho thu mua duyệt (giá lấy lại từ báo giá lúc gửi)."""
        self.ensure_one()
        self._check_state(("quoted",), _("gửi thu mua duyệt"))
        quote_line = self._target_quote_line().sudo()
        new_incl = price_incl_vat(quote_line.price_unit, quote_line.tax_rate) if quote_line else self.vendor_price_incl
        if not new_incl or quote_line.unavailable:
            raise UserError(_("NCC chưa có giá cho món này — hỏi lại NCC."))
        if not self._has_line_change() and same_money(new_incl, self.old_price_incl):
            raise UserError(_("NCC vẫn báo %s sau VAT — bằng giá trên đơn, không có gì để thu mua duyệt. Hỏi lại NCC lần "
                              "nữa hoặc bấm \"NCC giữ giá\".", money_text(new_incl)))
        # Dòng đơn sẽ lấy đúng VAT NCC báo — hoá đơn NCC xuất theo VAT đó. NCC để trống VAT = giữ VAT trên đơn.
        self._submit(new_incl, note, quote_line.vat or "")

    def _submit(self, new_incl, note, vat=""):
        """Chuyển thu mua duyệt: giá sau VAT sẽ áp new_incl, VAT vat (rỗng = giữ) + SL / mã sale đã chốt; việc cho thu
        mua trên đơn."""
        self.sudo().write({"state": "to_approve", "new_price_incl": new_incl, "apply_vat": vat or False,
                           "sale_note": (note or "").strip()[:255],
                           "submit_date": fields.Datetime.now(), "sale_user_id": self.env.uid})
        texts = self._texts()
        self.sudo().activity_id = self.purchase_order_id._hlv_schedule_buyer_activity(
            _("Sale gửi thay đổi dòng đơn — cần duyệt"),
            Markup("<p>%s</p>") % _("%(product)s: %(old)s → %(price)s (sau VAT)%(change)s. Bấm \"Đề xuất giá\" trên "
                                    "đơn để duyệt.", **texts),
            self.buyer_id,
        )
        self._post_order(Markup(_("Sale gửi duyệt %(product)s: %(old)s → <b>%(price)s</b> (sau VAT)%(change)s.")) % texts)

    def _sale_keep(self, note):
        """Sale báo NCC giữ giá cũ: đóng đề xuất, đơn giữ nguyên."""
        self.ensure_one()
        self._check_state(KEEP_FROM, _("báo NCC giữ giá"))
        note = (note or "").strip()[:255]
        self._close_requote()
        self._drop_new_quote_line()
        self.sudo().write({"state": "kept", "sale_note": note or False, "sale_user_id": self.env.uid})
        self._post_order(Markup(_("Sale báo NCC <b>giữ giá</b> %(product)s (%(old)s sau VAT)%(note)s — đơn giữ nguyên.")) % dict(
            self._texts(), note=(": " + note) if note else ""))

    # ------------------------------------------------------------------ thu mua duyệt
    def action_approve(self):
        """Thu mua duyệt: đổi giá / SL / mã trên đơn mua (một phiên bản mới của đơn — po_proposal_change), báo NCC +
        sale."""
        for proposal in self:
            proposal._check_state(("to_approve",), _("duyệt"))
            line = proposal.order_line_id
            if line.qty_invoiced:
                raise UserError(_("%s đã có hoá đơn NCC — không đổi giá trên đơn được nữa.", line.product_id.display_name))
            revision = proposal._apply_line_change()
            proposal.sudo().write({"state": "approved", "revision_id": revision.id, "decided_user_id": self.env.uid,
                                   "decided_date": fields.Datetime.now()})
            proposal._close_activity(_("Đã duyệt"))
            proposal._tell_sale(_("Thu mua duyệt %(product)s: %(price)s (sau VAT)%(change)s", **proposal._texts()))
        return True

    def action_reject(self):
        """Thu mua không duyệt giá sale gửi (bắt buộc lý do): đơn giữ nguyên, sale hỏi lại NCC hoặc báo giữ giá."""
        for proposal in self:
            proposal._check_state(("to_approve",), _("không duyệt"))
            if not (proposal.reject_reason or "").strip():
                raise UserError(_("Ghi lý do không duyệt để sale biết."))
            proposal.sudo().write({"state": "rejected", "decided_user_id": self.env.uid,
                                   "decided_date": fields.Datetime.now()})
            proposal._close_activity(_("Không duyệt: %s", proposal.reject_reason))
            proposal._tell_sale(_("Thu mua không duyệt giá %(product)s (%(reason)s) — hỏi lại NCC hoặc báo giữ giá",
                                  product=proposal.product_id.display_name, reason=proposal.reject_reason))
        return True

    def action_cancel(self):
        """Thu mua rút đề xuất (không cần đổi giá nữa)."""
        for proposal in self:
            proposal._check_state(OPEN_STATES, _("huỷ"))
            proposal._close_requote()
            proposal._drop_new_quote_line()
            proposal.sudo().write({"state": "cancel", "decided_user_id": self.env.uid,
                                   "decided_date": fields.Datetime.now()})
            proposal._close_activity(_("Thu mua huỷ đề xuất"))
            proposal._tell_sale(_("Thu mua huỷ đề xuất giá %s — không cần hỏi lại NCC", proposal.product_id.display_name))
        return True

    # ------------------------------------------------------------------ phụ
    def _check_state(self, states, action):
        if self.state not in states:
            raise UserError(_("Đề xuất giá %(name)s đang \"%(state)s\" — không %(action)s được.",
                              name=self.name, state=dict(PROPOSAL_STATES)[self.state], action=action))

    def _close_requote(self):
        """NCC không còn phải báo lại món này (đề xuất xong / huỷ) — khoá lại dòng báo giá."""
        lines = (self.sudo().quote_line_id | self.sudo().new_quote_line_id).filtered(
            lambda l: l.hlv_requote_proposal_id in self)
        lines._hlv_close_requote()

    def _texts(self):
        """Chữ dùng trong các tin: sản phẩm, đơn, giá (sau VAT, làm tròn tới đồng), lý do."""
        self.ensure_one()
        return {
            "product": self.product_id.display_name or "", "order": self.purchase_order_id.name or "",
            "old": money_text(self.old_price_incl), "new": money_text(self.suggested_price_incl),
            "vendor": money_text(self.vendor_price_incl), "price": money_text(self.new_price_incl),
            "note": self.buyer_note or "",
            "change": (" — " + self._change_text()) if self._has_line_change() else "",
        }

    def _buyer_wish_text(self):
        """Thu mua muốn gì: "gợi ý giá 300.000; SL 2; mã X" — "chỉ ghi lý do" khi không điền gì."""
        parts = []
        if self.suggested_price_incl:
            parts.append(_("gợi ý giá %s", money_text(self.suggested_price_incl)))
        if self.suggested_drop:
            parts.append(_("không mua nữa (SL %s → 0)", format_vn_number(self.old_qty)))
        elif self.suggested_qty:
            parts.append(_("SL %(old)s → %(new)s", old=format_vn_number(self.old_qty),
                           new=format_vn_number(self.suggested_qty)))
        if self.suggested_product_id:
            parts.append(_("đổi sang mã %s", self.suggested_product_id.display_name))
        if self.suggested_vat:
            parts.append(_("VAT %(old)s%% → %(new)s", old=format_vn_number(self.tax_rate),
                           new=vat_label(self.suggested_vat)))
        return "; ".join(parts) or _("chỉ ghi lý do")

    def _post_order(self, body):
        post_internal(self.purchase_order_id.sudo(), body, self.env.user.partner_id)

    def _post_inquiry(self, body, author=None):
        """Ghi chú nội bộ lên phiếu hỏi giá. author: res.partner (mặc định người đang thao tác; NCC báo lại từ trang
        công khai thì truyền NCC — người đang thao tác lúc đó là user công khai)."""
        if self.inquiry_id:
            post_internal(self.inquiry_id.sudo(), body, author or self.env.user.partner_id)

    def _tell_sale(self, event, source="buyer"):
        self.purchase_order_id._hlv_tell_sale(event, source)

    def _close_activity(self, feedback):
        if self.activity_id:
            self.activity_id.sudo().with_context(mail_activity_quick_update=True).action_feedback(feedback=feedback)


class PurchaseOrderPriceProposalMixin(models.Model):
    _inherit = "purchase.order"

    hlv_price_proposal_ids = fields.One2many("hlv.po.price.proposal", "purchase_order_id", string="Đề xuất giá")
    hlv_price_proposal_open_count = fields.Integer(string="Đề xuất giá đang mở",
                                                   compute="_compute_hlv_price_proposal_counts")
    hlv_price_proposal_approve_count = fields.Integer(string="Giá chờ thu mua duyệt",
                                                      compute="_compute_hlv_price_proposal_counts")

    @api.depends("hlv_price_proposal_ids.state")
    def _compute_hlv_price_proposal_counts(self):
        for order in self:
            states = order.hlv_price_proposal_ids.mapped("state")
            order.hlv_price_proposal_open_count = sum(1 for state in states if state in OPEN_STATES)
            order.hlv_price_proposal_approve_count = states.count("to_approve")

    def action_view_hlv_price_proposals(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("hlv_vendor_quotation.action_po_price_proposal")
        action["domain"] = [("purchase_order_id", "=", self.id)]
        action["context"] = {}
        return action
