# -*- coding: utf-8 -*-
"""Mở lại một món đã lên đơn mua trên báo giá của NCC để NCC báo lại giá — bước "Hỏi lại NCC" của đề xuất giá
(po_price_proposal.py). Món hỏi lại được NCC sửa dù đã đặt (vendor_quote_line._compute_vendor_locked); báo giá đã
đóng thì mở lại CHỈ cho món đó, NCC gửi xong (hoặc đề xuất đóng) thì trả báo giá về trạng thái cũ.
"""

from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError

from .price_proposal_utils import REQUOTE_DAYS, requote_restore_state


class VendorQuoteRequote(models.Model):
    _inherit = "hlv.vendor.quote"

    hlv_requote_prev_state = fields.Char(
        string="Trạng thái trước khi hỏi lại giá", readonly=True, copy=False,
        help="Báo giá đang mở cho NCC báo lại giá món thu mua đề xuất: trạng thái trước đó, để trả lại khi xong. "
             "\"done\" = báo giá đã đóng, chỉ mở món đang hỏi lại.",
    )

    def _hlv_open_quote(self):
        """Báo giá về "Chờ NCC báo giá" để NCC thấy việc cần làm (nhớ trạng thái cũ để trả lại khi xong); hạn đã qua
        thì gia hạn REQUOTE_DAYS ngày. Báo giá đã huỷ → UserError. Gọi nhiều lần không sao."""
        self.ensure_one()
        quote = self.sudo()
        if quote.state in ("draft", "cancel"):
            raise UserError(_("Báo giá %s đã huỷ — không hỏi lại NCC qua báo giá này được.", quote.name))
        vals = {"state": "sent"}
        if not quote.hlv_requote_prev_state:
            vals["hlv_requote_prev_state"] = quote.state
        today = quote._vendor_today()
        if quote.date_deadline and quote.date_deadline < today:
            vals["date_deadline"] = today + timedelta(days=REQUOTE_DAYS)
        quote.write(vals)

    def _hlv_open_requote(self, quote_line, proposal, qty):
        """Mở quote_line (thuộc báo giá này) cho NCC báo lại giá theo proposal, cho SL qty (SL sẽ mua của NCC này — sale
        có thể đã đổi; dòng đã lên đơn bị khoá nên SL trên báo giá không tự đổi theo phiếu)."""
        self._hlv_open_quote()
        vals = {"hlv_requote_proposal_id": proposal.id}
        if abs(quote_line.product_qty - qty) > 1e-6:
            vals["product_qty"] = qty
        quote_line.sudo().write(vals)

    def _vendor_submit(self, line_values, vendor_note, price_valid_until=False):
        """Món đang hỏi lại đã lên đơn mua: NCC phải báo giá, không báo "không có hàng" được (hết hàng là việc đổi SL
        đơn mua — nhắn bên mua). Gửi xong thì ghi giá NCC báo lại vào đề xuất."""
        requoted = self._vendor_lines().filtered(lambda l: l._hlv_requote_open())
        # Chỉ món ĐÃ đặt bắt buộc có giá; mã thay thế thu mua đề xuất thì NCC báo "không có hàng" được.
        refused = requoted.filtered(lambda l: (line_values.get(l.id) or {}).get("unavailable")
                                    and l.sudo().hlv_requote_proposal_id.quote_line_id == l)
        if refused:
            raise UserError(_(
                "%s đã đặt hàng, bên mua chỉ hỏi lại giá — nhập đơn giá (hết hàng thì nhắn bên mua trong khung trao đổi).",
                ", ".join(refused.mapped(lambda l: l.name or l.product_id.display_name)),
            ))
        result = super()._vendor_submit(line_values, vendor_note, price_valid_until)
        requoted._hlv_requote_answered()
        return result


class VendorQuoteLineRequote(models.Model):
    _inherit = "hlv.vendor.quote.line"

    def _hlv_requote_open(self):
        """Dòng đang chờ NCC báo lại giá (đề xuất giá ở bước "Chờ NCC báo lại"). sudo: tính vendor_locked cả khi sale
        (không có quyền đọc đề xuất giá) mở bảng so giá."""
        self.ensure_one()
        return self.sudo().hlv_requote_proposal_id.state == "vendor"

    def _hlv_requote_answered(self):
        """NCC vừa gửi lại báo giá: ghi giá vào đề xuất, khoá lại dòng."""
        for line in self:
            proposal = line.hlv_requote_proposal_id
            line._hlv_close_requote()
            proposal._vendor_answered(line)

    def _hlv_close_requote(self):
        """Khoá lại các dòng hỏi lại giá; báo giá không còn món nào hỏi lại thì về trạng thái cũ (requote_restore_state)."""
        quotes = self.quote_id.sudo()
        self.sudo().write({"hlv_requote_proposal_id": False})
        for quote in quotes.filtered("hlv_requote_prev_state"):
            if quote.line_ids.filtered("hlv_requote_proposal_id"):
                continue
            vals = {"hlv_requote_prev_state": False}
            restore = requote_restore_state(quote.hlv_requote_prev_state, quote.state)
            if restore:
                vals["state"] = restore
            quote.write(vals)
