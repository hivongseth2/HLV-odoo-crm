# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_line import DEFAULT_VENDOR_VAT, VAT_SELECTION
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import format_vn_number, price_incl_vat
from odoo.addons.hlv_vendor_quotation.services.notify import post_internal
from odoo.addons.hlv_vendor_quotation.services.price_reuse import recent_vendor_price
# Gửi Zalo OA cho sale: dùng lại đúng đường gửi của trang hỏi giá (cấu hình + mapping mã sale, công tắc trong Cài đặt).
from odoo.addons.hlv_vendor_quotation.services.sale_zalo import _send as send_sale_zalo

from ..services.proposal_apply import submit_values, vat_rate
from ..services.proposal_prompt import STATUS_OFFERED, STATUS_STOCK_ONLY, STATUS_UNAVAILABLE, price_incl

PROPOSAL_STATES = [
    ("draft", "Chờ sale duyệt"),
    ("applied", "Đã ghi vào báo giá"),
    ("rejected", "Đã bỏ"),
]
LINE_STATUSES = [
    (STATUS_OFFERED, "Có giá"),
    (STATUS_STOCK_ONLY, "Chỉ báo tồn kho"),
    (STATUS_UNAVAILABLE, "Hết hàng / không có"),
]
PRICE_SOURCES = [
    ("zalo", "NCC báo trên Zalo"),
    ("pricelist", "Bảng giá NCC"),
    ("reused", "Giá cũ còn hiệu lực"),
    ("none", "Chưa có giá"),
]
REVIEW_ROUTE = "/zalo-de-xuat"
# AI tự ghi đề xuất đủ chắc vào báo giá, không chờ sale duyệt (_auto_apply). Mặc định tắt.
AUTO_APPLY_PARAM = "hlv_vendor_zalo.ai_auto_apply"


class _ApplyFailed(Exception):
    """Tự ghi lỗi giữa chừng — chỉ để thoát savepoint (huỷ phần đã ghi), không ra khỏi _auto_apply."""


class ZaloProposal(models.Model):
    """AI đọc nhóm Zalo của NCC → đề xuất giá / tồn kho cho MỘT báo giá đang mở. Sale của phiếu duyệt trên trang
    /zalo-de-xuat/<id>, bấm "Ghi vào báo giá" mới ghi (như NCC tự gửi). Mỗi báo giá giữ một đề xuất đang chờ: AI đọc
    thêm tin mới thì cập nhật đề xuất đó."""

    _name = "hlv.zalo.proposal"
    _description = "Đề xuất báo giá từ Zalo (AI)"
    _order = "id desc"
    _rec_name = "quote_id"

    quote_id = fields.Many2one("hlv.vendor.quote", string="Báo giá NCC", required=True, index=True, ondelete="cascade")
    inquiry_id = fields.Many2one(related="quote_id.inquiry_id", string="Phiếu hỏi giá", store=True, index=True)
    partner_id = fields.Many2one(related="quote_id.partner_id", string="NCC", store=True, index=True)
    sale_code = fields.Char(related="quote_id.inquiry_id.sale_code", string="Mã sale", store=True)
    group_id = fields.Many2one("hlv.zalo.group", string="Nhóm Zalo", ondelete="set null")
    state = fields.Selection(PROPOSAL_STATES, string="Trạng thái", default="draft", required=True, index=True)
    summary = fields.Text(string="AI tóm tắt")
    line_ids = fields.One2many("hlv.zalo.proposal.line", "proposal_id", string="Dòng đề xuất")
    message_ids = fields.Many2many("hlv.zalo.message", string="Tin căn cứ")
    ai_model = fields.Char(string="Model AI", readonly=True)
    ai_run_at = fields.Datetime(string="AI đọc lúc", readonly=True)
    decided_by = fields.Many2one("res.users", string="Người duyệt", readonly=True)
    decided_at = fields.Datetime(string="Duyệt lúc", readonly=True)

    def _review_url(self):
        self.ensure_one()
        return f"{self.get_base_url()}{REVIEW_ROUTE}/{self.id}"

    def action_open_review_page(self):
        """Form backend chỉ để xem — duyệt / ghi làm trên trang /zalo-de-xuat/<id> (trang đó tự kiểm quyền)."""
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": f"{REVIEW_ROUTE}/{self.id}", "target": "new"}

    @api.model
    def _upsert_from_ai(self, group, quote, rows, summary, messages, model):
        """Ghi kết quả AI cho một báo giá: cập nhật đề xuất đang chờ (thay toàn bộ dòng — AI đọc lại cả đoạn hội thoại
        nên kết quả mới đã gồm cái cũ) hoặc tạo mới. Trả (đề xuất, có gì mới để báo sale không — mới tạo, hoặc NCC nói
        khác lần đọc trước)."""
        proposal = self.search([("quote_id", "=", quote.id), ("state", "=", "draft")], limit=1)
        created = not proposal
        before = proposal.line_ids._signature() if proposal else None
        vals = {
            "group_id": group.id, "summary": summary, "ai_model": model, "ai_run_at": fields.Datetime.now(),
            "message_ids": [(6, 0, messages.ids)],
            "line_ids": [(5, 0, 0)] + [(0, 0, self.env["hlv.zalo.proposal.line"]._vals_from_ai(row, messages))
                                       for row in rows],
        }
        if created:
            proposal = self.create(dict(vals, quote_id=quote.id))
        else:
            proposal.write(vals)
        return proposal, created or proposal.line_ids._signature() != before

    def _notify_sale(self, applied=False):
        """Báo sale của phiếu có đề xuất mới (applied: AI đã tự ghi vào báo giá): ghi chú nội bộ trên phiếu + Zalo OA
        (nếu đang bật báo Zalo cho sale)."""
        for proposal in self:
            url = proposal._review_url()
            action = "— AI đã tự ghi giá vào" if applied else "đã trả lời cho"
            text = f"🤖 AI đọc Zalo nhóm {proposal.group_id.name}: NCC {proposal.partner_id.display_name} {action} " \
                   f"{proposal.quote_id.name} — {proposal.summary or 'xem đề xuất'}"
            link = "Xem lại" if applied else "Duyệt đề xuất"
            post_internal(proposal.inquiry_id, Markup("<p>%s</p><p><a href='%s'>%s</a></p>") % (text, url, link))
            send_sale_zalo(proposal.quote_id, [proposal.sale_code], f"{text}\n{link}: {url}")

    def _open_lines(self):
        """Dòng báo giá còn ghi được (chưa lên đơn mua) — đúng các dòng trang duyệt hiện và _vendor_submit nhận."""
        self.ensure_one()
        return self.quote_id._vendor_lines().filtered(lambda l: not l.vendor_locked)

    def _apply_form(self, form):
        """Ghi vào báo giá bằng đúng hàm NCC dùng khi tự gửi (_vendor_submit — cùng luật: mọi dòng đang mở phải có giá +
        VAT, hoặc hết hàng). form: ô trang duyệt theo dòng ("price_<id>", "vat_<id>", "discount_<id>", "available_<id>",
        "backorder_date_<id>", "delivery_days_<id>", "na_<id>"). Trả danh sách lỗi ([] = đã ghi)."""
        self.ensure_one()
        quote = self.quote_id
        today = quote._vendor_today()
        values, errors = {}, []
        for line in self._open_lines():
            raw_date = (form.get(f"backorder_date_{line.id}") or "").strip()
            try:
                backorder = fields.Date.to_date(raw_date) if raw_date else None
            except ValueError:
                errors.append(f"{line.name}: ngày hẹn \"{raw_date}\" không đọc được")
                continue
            line_values, error = submit_values(line.product_qty, {
                "unavailable": bool(form.get(f"na_{line.id}")), "price": form.get(f"price_{line.id}"),
                "vat": form.get(f"vat_{line.id}"), "discount": form.get(f"discount_{line.id}"),
                "available": form.get(f"available_{line.id}"), "backorder_date": backorder,
                "delivery_days": form.get(f"delivery_days_{line.id}"),
            }, today, {"vendor_note": line.vendor_note, "invoice_name": line.invoice_name})
            if error:
                errors.append(f"{line.product_id.default_code or line.name}: {error}")
            else:
                values[line.id] = line_values
        if errors:
            return errors
        # Hiệu lực giá cũ đã qua thì để trống — _vendor_submit tự đặt 7 ngày (ngày đã qua là lỗi).
        valid_until = quote.price_valid_until if quote.price_valid_until and quote.price_valid_until >= today else False
        try:
            quote._vendor_submit(values, quote.vendor_note or "", valid_until)
        except UserError as exc:
            return [exc.args[0]]
        self._mark("applied")
        return []

    def _auto_apply(self):
        """Cài đặt bật "AI tự ghi" và đề xuất đủ chắc (_is_sure) thì ghi thẳng vào báo giá, báo sale "đã tự ghi". Trả
        True khi đã ghi; False → để sale duyệt như thường (người gọi tự báo sale)."""
        self.ensure_one()
        if self.env["ir.config_parameter"].sudo().get_param(AUTO_APPLY_PARAM) != "True" or not self._is_sure():
            return False
        form = {}
        for line in self.line_ids:
            form.update({f"{key}_{line.quote_line_id.id}": value for key, value in line._form_values().items()})
        try:
            # Ghi lỗi (VD báo giá vừa đóng) thì huỷ hết phần đã ghi — đề xuất nguyên trạng chờ sale duyệt.
            with self.env.cr.savepoint():
                if self._apply_form(form):
                    raise _ApplyFailed()
        except _ApplyFailed:
            return False
        self._log_applied(auto=True)
        self._notify_sale(applied=True)
        return True

    def _is_sure(self):
        """Đủ chắc để AI tự ghi: báo giá còn chờ NCC báo (chưa có giá đã ghi — không ghi đè), đề xuất phủ MỌI dòng còn
        mở, dòng nào cũng "chắc chắn" và là điều NCC nói thẳng: giá NCC báo trên Zalo, VAT NCC nói, rõ trước / sau VAT —
        hoặc NCC báo hết hàng. Giá suy ra (bảng giá, giá cũ khi NCC chỉ báo tồn kho) luôn để sale duyệt."""
        self.ensure_one()
        if self.quote_id.state != "sent" or set(self._open_lines().ids) != set(self.line_ids.quote_line_id.ids):
            return False
        return all(
            line.confidence == "high" and (
                line.status == STATUS_UNAVAILABLE
                or (line.status == STATUS_OFFERED and line.price_source == "zalo" and line.price_incl
                    and not line.vat_assumed and not line.basis_unknown))
            for line in self.line_ids)

    def _mark(self, state):
        self.write({"state": state, "decided_by": self.env.user.id, "decided_at": fields.Datetime.now()})

    def _log_applied(self, auto=False):
        """Ghi lên báo giá: giá / tồn kho lấy từ Zalo, ai duyệt (auto: AI tự ghi) — để sau này tra được nguồn."""
        self.ensure_one()
        who = "AI tự ghi (mọi dòng chắc chắn)" if auto else f"AI đề xuất, {self.env.user.name} duyệt"
        post_internal(self.quote_id, Markup("<p>%s</p>") % (
            f"Giá / tồn kho ghi từ Zalo nhóm {self.group_id.name or '?'} — {who} ({len(self.message_ids)} tin căn cứ)."))


class ZaloProposalLine(models.Model):
    """Điều AI đọc được cho một dòng báo giá. Trang duyệt điền sẵn từ đây; sale sửa trên trang, giá trị trên trang mới
    là giá trị ghi vào báo giá."""

    _name = "hlv.zalo.proposal.line"
    _description = "Dòng đề xuất báo giá từ Zalo"
    _order = "id"

    proposal_id = fields.Many2one("hlv.zalo.proposal", required=True, index=True, ondelete="cascade")
    quote_line_id = fields.Many2one("hlv.vendor.quote.line", string="Dòng báo giá", required=True, ondelete="cascade")
    status = fields.Selection(LINE_STATUSES, string="NCC nói", required=True)
    price_incl = fields.Float(string="Giá sau VAT (trước CK)", digits=(16, 2))
    discount = fields.Float(string="% CK")
    vat = fields.Selection(VAT_SELECTION, string="VAT")
    vat_assumed = fields.Boolean(string="VAT tự điền", help="NCC không nói VAT — lấy VAT của dòng / mặc định, cần xem lại.")
    basis_unknown = fields.Boolean(string="Không rõ trước / sau VAT",
                                   help="NCC không nói giá đã gồm VAT chưa — đang coi là giá sau VAT.")
    price_source = fields.Selection(PRICE_SOURCES, string="Nguồn giá", default="none")
    available_qty = fields.Float(string="Sẵn", default=-1.0, help="-1 = có đủ / NCC không nói số.")
    backorder_date = fields.Date(string="Hẹn giao phần thiếu")
    delivery_days = fields.Integer(string="Giao (ngày)")
    note = fields.Char(string="Ghi chú")
    evidence = fields.Text(string="NCC nói")
    # Bảng riêng: đề xuất cũng có Many2many tới tin (message_ids) — tên bảng mặc định dễ đụng nhau.
    evidence_message_ids = fields.Many2many("hlv.zalo.message", "hlv_zalo_proposal_line_evidence_rel", "line_id",
                                            "message_id", string="Tin căn cứ")
    confidence = fields.Selection([("high", "Chắc chắn"), ("low", "Cần xem lại")], string="Độ chắc")

    def _form_values(self):
        """Điều AI đọc được → giá trị ô trang duyệt (chuỗi như sale gõ): trang điền sẵn, AI tự ghi dùng thẳng."""
        self.ensure_one()
        return {
            "na": self.status == STATUS_UNAVAILABLE,
            "price": format_vn_number(self.price_incl) if self.price_incl else "",
            "vat": self.vat or "", "discount": format_vn_number(self.discount) if self.discount else "",
            "available": format_vn_number(self.available_qty) if self.available_qty >= 0 else "",
            "backorder_date": self.backorder_date.isoformat() if self.backorder_date else "",
            "delivery_days": str(self.delivery_days or ""),
        }

    def _signature(self):
        """Điều NCC nói, gọn để so hai lần AI đọc — giống nhau thì không báo sale lần nữa."""
        return sorted((l.quote_line_id.id, l.status, l.price_incl, l.discount, l.vat, l.available_qty,
                       str(l.backorder_date or "")) for l in self)

    @api.model
    def _vals_from_ai(self, row, messages):
        """Một dòng AI trả (proposal_prompt.clean_line) → giá trị lưu. NCC chỉ báo tồn kho: lấy giá Bảng giá NCC đang
        hiệu lực, không có thì giá NCC này báo gần nhất còn hiệu lực; không có nữa thì để trống cho sale nhập.
        Tin căn cứ chỉ nhận số # nằm trong đoạn hội thoại đã đưa AI (messages) — AI bịa số thì bỏ."""
        line = self.env["hlv.vendor.quote.line"].browse(row["line_id"])
        vat = row["vat"] or line.vat or DEFAULT_VENDOR_VAT
        vals = {
            "quote_line_id": line.id, "status": row["status"], "vat": vat, "vat_assumed": not row["vat"],
            "available_qty": row["available_qty"], "backorder_date": row["backorder_date"] or False,
            "delivery_days": row["delivery_days"], "note": row["note"], "evidence": row["evidence"],
            "confidence": row["confidence"], "discount": row["discount_pct"],
            "evidence_message_ids": [(6, 0, [i for i in row["evidence_msg_ids"] if i in messages.ids])],
        }
        if row["status"] == STATUS_OFFERED and row["price"]:
            vals.update(price_incl=price_incl(row["price"], row["price_basis"], vat_rate(vat)), price_source="zalo",
                        basis_unknown=row["price_basis"] == "unknown")
        elif row["status"] == STATUS_STOCK_ONLY:
            vals.update(self._listed_price(line, vat) or self._reused_price(line, vat))
        return vals

    def _listed_price(self, line, vat):
        """Giá Bảng giá NCC đang hiệu lực (file giá NCC gửi, nhập ở hlv_vendor_import) — {} nếu không có. Chiết khấu
        giữ đúng điều NCC nói trên Zalo (bảng giá là giá niêm yết; CK mỗi lần một khác)."""
        # hlv_vendor_import không bắt buộc cài: chưa có module đó thì bỏ qua bảng giá.
        if "hlv.vendor.price" not in self.env:
            return {}
        listed = self.env["hlv.vendor.price"].sudo().current_price(
            line.quote_id.partner_id, line.product_id, line.quote_id._vendor_today())
        if not listed:
            return {}
        listed_vat = listed.vat or vat
        gross = listed.price_incl if listed.vat or not listed.price else price_incl_vat(listed.price, vat_rate(listed_vat))
        return {"price_incl": round(gross), "vat": listed_vat, "vat_assumed": not listed.vat, "price_source": "pricelist"}

    @staticmethod
    def _reused_price(line, vat):
        """Giá chính NCC này báo gần nhất còn hiệu lực (price_reuse — như chip "giá cũ" trên trang NCC) — {} nếu không."""
        reference = recent_vendor_price(line)
        if not reference:
            return {}
        return {"price_incl": round(price_incl_vat(reference.list_price or reference.price_unit, reference.tax_rate)),
                "discount": reference.discount if reference.list_price else 0.0,
                "vat": reference.vat or vat, "vat_assumed": False, "price_source": "reused"}
