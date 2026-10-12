# -*- coding: utf-8 -*-
"""Yêu cầu thay đổi đơn mua của NCC (phiên bản / snapshot): NCC đổi SL / đơn giá / ngày giao trên trang NCC
(VD bỗng hết hàng) → không áp ngay vào đơn mà tạo một yêu cầu lưu giá trị cũ / mới từng dòng, chờ thu mua
duyệt — duyệt mới áp vào đơn. Trạng thái đơn nào cần duyệt: Cài đặt (mặc định mọi trạng thái). Chỉ đổi ngày giao
trên đơn đã xác nhận thì tự cập nhật (purchase_order_delivery._vendor_set_due_dates).

Mọi bước ghi vào khung trao đổi của đơn (NCC + bên mua cùng xem); báo thu mua bằng hoạt động trong Odoo, không email.
"""

from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.chat_bus import notify_order_status
from ..services.vendor_chat import post_chat
from .delivery_utils import due_datetime, local_day
from .purchase_order import CONFIRMED_STATES, VENDOR_ORDER_STATES
from .revision_utils import change_text, is_dates_only, line_change_error, line_changes, needs_approval
from .vendor_quote_utils import DATE_FMT, local_date_text, parse_states, price_incl_vat, split_unit_price

REVISION_STATES = [
    ("pending", "Chờ thu mua duyệt"),
    ("approved", "Đã duyệt"),
    ("rejected", "Không duyệt"),
    ("withdrawn", "NCC đã rút"),
    ("applied", "Áp ngay (không cần duyệt)"),
]
# Cài đặt → Mua hàng → Hỏi giá NCC: trạng thái đơn mua mà yêu cầu của NCC phải chờ thu mua duyệt.
REVISION_STATES_PARAM = "hlv_vendor_quotation.revision_states"
DEFAULT_REVISION_STATES = tuple(state for state, _label in VENDOR_ORDER_STATES)
# Giá trị lưu khi bỏ tick hết (không trạng thái nào cần duyệt): lưu rỗng thì Odoo xoá tham số → về mặc định.
NO_REVISION_STATES = "none"
# Yêu cầu đã áp vào đơn — mỗi cái tạo một phiên bản mới của đơn.
APPLIED_STATES = ("approved", "applied")


def tax_rate_of(order_line):
    """% thuế (loại %) của dòng đơn mua — để đổi giá NCC gõ (sau VAT) ra giá chưa VAT lưu trên đơn."""
    return sum(order_line.taxes_id.filtered(lambda t: t.amount_type == "percent").mapped("amount"))


class PurchaseOrderRevision(models.Model):
    _name = "hlv.po.revision"
    _description = "Yêu cầu thay đổi đơn mua của NCC"
    _order = "purchase_order_id, number desc"

    purchase_order_id = fields.Many2one("purchase.order", string="Đơn mua", required=True, ondelete="cascade", index=True)
    partner_id = fields.Many2one(related="purchase_order_id.partner_id", string="Nhà cung cấp")
    number = fields.Integer(string="Yêu cầu số", readonly=True)
    state = fields.Selection(REVISION_STATES, string="Trạng thái", default="pending", required=True, readonly=True)
    vendor_note = fields.Text(string="Ghi chú của NCC", readonly=True)
    reject_reason = fields.Char(string="Lý do không duyệt")
    author_partner_id = fields.Many2one("res.partner", string="NCC yêu cầu", readonly=True)
    decided_user_id = fields.Many2one("res.users", string="Người duyệt", readonly=True)
    decided_date = fields.Datetime(string="Duyệt lúc", readonly=True)
    activity_id = fields.Many2one("mail.activity", string="Hoạt động", readonly=True, ondelete="set null")
    line_ids = fields.One2many("hlv.po.revision.line", "revision_id", string="Thay đổi")
    summary = fields.Text(string="Tóm tắt", compute="_compute_summary")
    # Bản chụp mọi dòng của đơn ngay trước / sau khi áp (PurchaseOrderRevisionMixin._hlv_snapshot) — NCC xem lại
    # từng phiên bản cũ. Không dựng ngược từ đơn hiện tại được: thu mua còn sửa tay đơn ngoài các yêu cầu.
    snapshot_before = fields.Json(string="Bản chụp trước khi áp", readonly=True, copy=False)
    snapshot_after = fields.Json(string="Bản chụp sau khi áp", readonly=True, copy=False)

    @api.depends("line_ids")
    def _compute_summary(self):
        for revision in self:
            revision.summary = "\n".join(revision.line_ids.mapped(lambda l: l._change_text()))

    def _change_texts(self):
        return self.line_ids.mapped(lambda l: l._change_text())

    # ------------------------------------------------------------------ thu mua duyệt / không duyệt
    def action_approve(self):
        """Thu mua duyệt: áp SL / giá / ngày yêu cầu vào đơn mua, báo NCC trên khung trao đổi."""
        for revision in self:
            revision._check_pending()
            revision._apply()
            revision.write({"state": "approved", "decided_user_id": self.env.uid, "decided_date": fields.Datetime.now()})
            revision._close_activity(_("Đã duyệt"))
            revision._log(_("Thu mua đã DUYỆT yêu cầu số %(n)s — đơn đã cập nhật:\n%(items)s",
                            n=revision.number, items=revision._bullet_text()), self.env.user.partner_id, from_vendor=False)
            revision._tell_sale(_("Thu mua duyệt thay đổi đơn của NCC: %s", "; ".join(revision._change_texts())), "buyer")
        return True

    def action_reject(self):
        """Thu mua không duyệt (bắt buộc ghi lý do): đơn giữ nguyên, báo NCC lý do."""
        for revision in self:
            revision._check_pending()
            if not (revision.reject_reason or "").strip():
                raise UserError(_("Ghi lý do không duyệt để NCC biết."))
            revision.write({"state": "rejected", "decided_user_id": self.env.uid, "decided_date": fields.Datetime.now()})
            revision._close_activity(_("Không duyệt: %s", revision.reject_reason))
            revision._log(_("Thu mua KHÔNG DUYỆT yêu cầu số %(n)s — đơn giữ nguyên. Lý do: %(reason)s",
                            n=revision.number, reason=revision.reject_reason), self.env.user.partner_id, from_vendor=False)
            revision._tell_sale(_("Thu mua không duyệt thay đổi đơn của NCC (%s)", revision.reject_reason), "buyer")
        return True

    def _vendor_withdraw(self, vendor_partner):
        """NCC rút yêu cầu còn chờ duyệt (để sửa lại / không đổi nữa)."""
        self.ensure_one()
        self._check_pending()
        self.state = "withdrawn"
        self._close_activity(_("NCC đã rút yêu cầu"))
        self._log(_("NCC rút yêu cầu số %s.", self.number), vendor_partner, from_vendor=True)

    def _check_pending(self):
        if self.state != "pending":
            raise UserError(_("Yêu cầu số %s không còn chờ duyệt.", self.number))

    # ------------------------------------------------------------------ áp vào đơn
    def _apply(self):
        """Ghi giá trị mới lên dòng đơn mua. Đơn đã khóa: mở khóa để ghi rồi khóa lại."""
        order = self.purchase_order_id.sudo()
        if order.state == "cancel":
            raise UserError(_("Đơn %s đã hủy — không áp được.", order.name))
        locked = order.state == "done"
        if locked:
            order.button_unlock()
        self.snapshot_before = order._hlv_snapshot()
        for line in self.line_ids:
            line._apply()
        self.snapshot_after = order._hlv_snapshot()
        if locked:
            order.button_done()

    # ------------------------------------------------------------------ báo
    def _bullet_text(self):
        return "\n".join(f"- {text}" for text in self._change_texts())

    def _log(self, text, author, from_vendor):
        """Ghi vào khung trao đổi của đơn (NCC + bên mua cùng xem) — không gọi tên ai, không email."""
        post_chat(self.purchase_order_id, text, author, from_vendor=from_vendor, notify=False)

    def _tell_sale(self, event, source):
        """Báo trang sale (chuông / popup / Zalo). source: "vendor" (NCC gửi / áp ngay) hoặc "buyer" (thu mua quyết)."""
        order = self.purchase_order_id.sudo()
        order.write({"hlv_vendor_event": event, "hlv_vendor_status_date": fields.Datetime.now(),
                     "hlv_vendor_event_source": source})
        notify_order_status(order)

    def _notify_buyer(self):
        """Hoạt động "cần duyệt" cho người mua của đơn (không có thì người tạo đơn). mail_activity_quick_update: không
        gửi email báo giao việc — thu mua thấy ở biểu tượng hoạt động trong Odoo."""
        order = self.purchase_order_id.sudo()
        buyer = order.user_id or order.create_uid
        if not buyer:
            return
        self.activity_id = order.with_context(mail_activity_quick_update=True).activity_schedule(
            "mail.mail_activity_data_todo",
            summary=_("NCC yêu cầu thay đổi đơn — cần duyệt"),
            note=Markup("<p>%s</p><ul>%s</ul>") % (
                _("Yêu cầu số %s của NCC (bấm nút \"Yêu cầu NCC chờ duyệt\" trên đơn để duyệt):", self.number),
                Markup("").join(Markup("<li>%s</li>") % text for text in self._change_texts()),
            ),
            user_id=buyer.id,
        )

    def _close_activity(self, feedback):
        if self.activity_id:
            self.activity_id.sudo().with_context(mail_activity_quick_update=True).action_feedback(feedback=feedback)


class PurchaseOrderRevisionLine(models.Model):
    _name = "hlv.po.revision.line"
    _description = "Dòng yêu cầu thay đổi đơn mua"

    revision_id = fields.Many2one("hlv.po.revision", required=True, ondelete="cascade", index=True)
    order_line_id = fields.Many2one("purchase.order.line", string="Dòng đơn mua", required=True, ondelete="cascade")
    name = fields.Char(string="Hàng hóa", readonly=True)
    uom_name = fields.Char(string="ĐVT", readonly=True)
    tax_rate = fields.Float(string="% thuế", readonly=True)
    old_qty = fields.Float(string="SL cũ", digits="Product Unit of Measure", readonly=True)
    new_qty = fields.Float(string="SL mới", digits="Product Unit of Measure", readonly=True)
    old_price_unit = fields.Float(string="Đơn giá cũ (chưa VAT)", digits="Product Price", readonly=True)
    new_price_unit = fields.Float(string="Đơn giá mới (chưa VAT)", digits="Product Price", readonly=True)
    old_date = fields.Date(string="Ngày giao cũ", readonly=True)
    new_date = fields.Date(string="Ngày giao mới", readonly=True)

    def _changes(self):
        """Thay đổi của dòng (revision_utils.line_changes) — giá so theo SAU VAT như NCC gõ."""
        self.ensure_one()
        return line_changes(
            self.old_qty, self.new_qty, price_incl_vat(self.old_price_unit, self.tax_rate),
            price_incl_vat(self.new_price_unit, self.tax_rate), self.old_date, self.new_date,
        )

    def _change_text(self):
        return change_text(self.name, self._changes(), self.uom_name or "")

    def _apply(self):
        changes = self._changes()
        po_line = self.order_line_id.sudo()
        vals = {}
        if "qty" in changes:
            # Đổi SL làm Odoo tính lại đơn giá + ngày giao theo bảng giá NCC (_compute_price_unit_and_date_planned_and_name)
            # — ghi kèm giá / ngày đang có trong cùng một write để Odoo không tính đè.
            vals.update(product_qty=self.new_qty, price_unit=po_line.price_unit, date_planned=po_line.date_planned)
        if "price" in changes:
            vals["price_unit"] = self.new_price_unit
        if vals:
            po_line.write(vals)
        if "price" in changes:
            # Báo giá NCC đổi theo — sale tra / hỏi lại giá thấy giá mới nhất NCC đã sửa.
            self.env["hlv.vendor.quote.line"]._hlv_follow_order_price(
                po_line, self.new_price_unit, self.revision_id.purchase_order_id.name)
        if "day" in changes:
            when = due_datetime(self.new_date, po_line.date_planned)
            po_line._update_date_planned(when)
            po_line.move_ids.filtered(lambda m: m.state not in ("done", "cancel")).write({"date": when})


class PurchaseOrderRevisionMixin(models.Model):
    _inherit = "purchase.order"

    hlv_revision_ids = fields.One2many("hlv.po.revision", "purchase_order_id", string="Yêu cầu của NCC")
    hlv_revision_pending_count = fields.Integer(string="Yêu cầu chờ duyệt", compute="_compute_hlv_revision_pending_count")

    @api.depends("hlv_revision_ids.state")
    def _compute_hlv_revision_pending_count(self):
        for order in self:
            order.hlv_revision_pending_count = len(order.hlv_revision_ids.filtered(lambda r: r.state == "pending"))

    def action_view_hlv_revisions(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("hlv_vendor_quotation.action_po_revision")
        action["domain"] = [("purchase_order_id", "=", self.id)]
        action["context"] = {"search_default_filter_pending": 1}
        return action

    @api.model
    def _hlv_revision_states(self):
        """Trạng thái đơn mua mà yêu cầu của NCC phải chờ thu mua duyệt (Cài đặt; chưa cấu hình → mọi trạng thái)."""
        param = self.env["ir.config_parameter"].sudo().get_param(REVISION_STATES_PARAM)
        if param == NO_REVISION_STATES:
            return ()
        return parse_states(param, list(DEFAULT_REVISION_STATES), DEFAULT_REVISION_STATES)

    def _hlv_revision_info(self):
        """Yêu cầu của NCC cho trang NCC: yêu cầu đang chờ, lịch sử (mới trước), phiên bản hiện tại (1 + số yêu cầu đã
        áp), sửa được không, giá sau VAT từng dòng (điền sẵn ô sửa giá)."""
        self.ensure_one()
        order = self.sudo()
        pending = order._hlv_revision_pending()
        labels = dict(REVISION_STATES)
        lines = order.order_line.filtered(lambda l: not l.display_type)
        # v1 = đơn gốc; mỗi yêu cầu đã áp (theo thứ tự) tạo bản kế tiếp.
        applied = order.hlv_revision_ids.filtered(lambda r: r.state in APPLIED_STATES).sorted("number")
        version_of = {revision.id: index + 2 for index, revision in enumerate(applied)}
        return {
            "pending": {"id": pending.id, "number": pending.number, "texts": pending._change_texts(),
                        "note": pending.vendor_note or ""} if pending else None,
            "pending_lines": {l.order_line_id.id: l._change_text() for l in pending.line_ids},
            "history": [{
                "number": r.number, "state": r.state, "state_label": labels[r.state], "at": r.create_date,
                "texts": r._change_texts(), "note": r.vendor_note or "", "reason": r.reject_reason or "",
                "version": version_of.get(r.id), "snapshot": r.snapshot_after or None,
            } for r in order.hlv_revision_ids.sorted("number", reverse=True)],
            "version": 1 + len(applied),
            "original": applied[:1].snapshot_before or None,
            "has_original": bool(applied),
            "editable": order.state != "cancel" and not pending,
            "prices": {l.id: price_incl_vat(l.price_unit, tax_rate_of(l)) for l in lines},
        }

    def _hlv_snapshot(self):
        """Bản chụp các dòng hàng của đơn cho lịch sử phiên bản trên trang NCC: {"lines": [{name, qty, uom, price
        (đơn giá sau VAT), date ("dd/mm/YYYY" giờ VN, "" nếu không có), total (thành tiền sau VAT)}], "total"}."""
        self.ensure_one()
        return {
            "lines": [{
                "name": line.name or line.product_id.display_name, "qty": line.product_qty,
                "uom": line.product_uom.name or "", "price": price_incl_vat(line.price_unit, tax_rate_of(line)),
                "date": local_date_text(line.date_planned, DATE_FMT), "total": line.price_total,
            } for line in self.order_line.filtered(lambda l: not l.display_type)],
            "total": self.amount_total,
        }

    def _hlv_revision_pending(self):
        self.ensure_one()
        return self.sudo().hlv_revision_ids.filtered(lambda r: r.state == "pending")[:1]

    def _vendor_propose_changes(self, edits, note, vendor_partner):
        """NCC đổi SL / đơn giá (sau VAT) / ngày giao của các dòng. edits: {id dòng: {"qty", "price", "day"}} — giá trị
        None = không sửa ô đó. Trả "pending" (tạo yêu cầu chờ duyệt), "applied" (áp ngay — trạng thái không cần duyệt)
        hoặc "dates" (đơn đã xác nhận, chỉ đổi ngày — tự cập nhật). Không đổi gì / giá trị sai → UserError."""
        self.ensure_one()
        order = self.sudo()
        if order.state == "cancel":
            raise UserError(_("Đơn %s đã hủy.", order.name))
        pending = order._hlv_revision_pending()
        if pending:
            raise UserError(_("Yêu cầu số %s đang chờ thu mua duyệt — rút yêu cầu đó trước khi gửi yêu cầu mới.", pending.number))
        collected = order._hlv_collect_changes(edits)
        changes_list = [changes for _line, _tax, changes in collected]
        confirmed = order.state in CONFIRMED_STATES
        if confirmed and is_dates_only(changes_list):
            order._vendor_set_due_dates({line.id: changes["day"][1] for line, _tax, changes in collected}, vendor_partner)
            return "dates"
        revision = order._hlv_create_revision(collected, note, vendor_partner)
        if needs_approval(changes_list, order.state, order._hlv_revision_states(), confirmed):
            revision._notify_buyer()
            revision._log(_("NCC yêu cầu thay đổi đơn (yêu cầu số %(n)s) — chờ thu mua duyệt:\n%(items)s%(note)s",
                            n=revision.number, items=revision._bullet_text(),
                            note=_("\nGhi chú: %s", note) if note else ""), vendor_partner, from_vendor=True)
            revision._tell_sale(_("NCC yêu cầu thay đổi đơn (chờ thu mua duyệt): %s", "; ".join(revision._change_texts())), "vendor")
            return "pending"
        revision._apply()
        revision.state = "applied"
        revision._log(_("NCC thay đổi đơn (áp ngay — trạng thái đơn không cần duyệt):\n%(items)s%(note)s",
                        items=revision._bullet_text(), note=_("\nGhi chú: %s", note) if note else ""),
                      vendor_partner, from_vendor=True)
        revision._tell_sale(_("NCC thay đổi đơn: %s", "; ".join(revision._change_texts())), "vendor")
        return "applied"

    def _hlv_collect_changes(self, edits):
        """[(dòng đơn mua, % thuế, thay đổi)] cho các dòng NCC thật sự đổi; kiểm từng giá trị."""
        today = self.env["hlv.vendor.quote"]._vendor_today()
        lines = self.order_line.filtered(lambda l: not l.display_type)
        collected = []
        for line_id, edit in edits.items():
            line = lines.filtered(lambda l, i=line_id: l.id == i)
            if not line:
                raise UserError(_("Dòng hàng không thuộc đơn %s.", self.name))
            error = line_change_error(edit.get("qty"), line.qty_received, edit.get("price"), edit.get("day"), today)
            if error:
                raise UserError(_("%(product)s: %(error)s.", product=line.product_id.display_name, error=error))
            tax = tax_rate_of(line)
            changes = line_changes(line.product_qty, edit.get("qty"), price_incl_vat(line.price_unit, tax),
                                   edit.get("price"), local_day(line.date_planned), edit.get("day"))
            if changes:
                collected.append((line, tax, changes))
        if not collected:
            raise UserError(_("Chưa thay đổi gì — sửa số lượng, đơn giá hoặc ngày giao rồi gửi lại."))
        return collected

    def _hlv_create_revision(self, collected, note, vendor_partner):
        """Snapshot: lưu giá trị cũ / mới từng dòng (giá mới đổi từ sau VAT ra chưa VAT theo thuế của dòng)."""
        number = len(self.hlv_revision_ids) + 1
        line_vals = []
        for line, tax, changes in collected:
            new_price = line.price_unit
            if "price" in changes:
                new_price = split_unit_price(changes["price"][1], tax)[0]
            line_vals.append((0, 0, {
                "order_line_id": line.id, "name": line.product_id.display_name, "uom_name": line.product_uom.name,
                "tax_rate": tax, "old_qty": line.product_qty, "new_qty": changes.get("qty", (0, line.product_qty))[1],
                "old_price_unit": line.price_unit, "new_price_unit": new_price,
                "old_date": local_day(line.date_planned), "new_date": changes.get("day", (0, local_day(line.date_planned)))[1],
            }))
        return self.env["hlv.po.revision"].sudo().create({
            "purchase_order_id": self.id, "number": number, "vendor_note": (note or "").strip() or False,
            "author_partner_id": vendor_partner.id if vendor_partner else False, "line_ids": line_vals,
        })
