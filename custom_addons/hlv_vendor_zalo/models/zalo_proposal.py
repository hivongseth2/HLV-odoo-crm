# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_line import DEFAULT_VENDOR_VAT, VAT_SELECTION
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import price_incl_vat
from odoo.addons.hlv_vendor_quotation.services.notify import post_internal
from odoo.addons.hlv_vendor_quotation.services.price_reuse import recent_vendor_price
# Gửi Zalo OA cho sale: dùng lại đúng đường gửi của trang hỏi giá (cấu hình + mapping mã sale, công tắc trong Cài đặt).
from odoo.addons.hlv_vendor_quotation.services.sale_zalo import _send as send_sale_zalo

from ..services.proposal_apply import vat_rate
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

    def _notify_sale(self):
        """Báo sale của phiếu có đề xuất mới: ghi chú nội bộ trên phiếu + Zalo OA (nếu đang bật báo Zalo cho sale)."""
        for proposal in self:
            url = proposal._review_url()
            text = f"🤖 AI đọc Zalo nhóm {proposal.group_id.name}: NCC {proposal.partner_id.display_name} đã trả lời " \
                   f"cho {proposal.quote_id.name} — {proposal.summary or 'xem đề xuất'}"
            post_internal(proposal.inquiry_id, Markup("<p>%s</p><p><a href='%s'>Duyệt đề xuất</a></p>") % (text, url))
            send_sale_zalo(proposal.quote_id, [proposal.sale_code], f"{text}\nDuyệt: {url}")

    def _mark(self, state):
        self.write({"state": state, "decided_by": self.env.user.id, "decided_at": fields.Datetime.now()})

    def _log_applied(self):
        """Ghi lên báo giá: giá / tồn kho lấy từ Zalo, ai duyệt — để sau này tra được nguồn."""
        self.ensure_one()
        post_internal(self.quote_id, Markup("<p>%s</p>") % (
            f"Giá / tồn kho ghi từ Zalo nhóm {self.group_id.name or '?'} — AI đề xuất, {self.env.user.name} duyệt "
            f"({len(self.message_ids)} tin căn cứ)."))


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
