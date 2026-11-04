# -*- coding: utf-8 -*-
"""Đề xuất của thu mua đổi cả SỐ LƯỢNG / MÃ HÀNG của dòng đơn mua, không chỉ giá — phần thêm vào hlv.po.price.proposal.

Thu mua ghi SL / mã muốn đổi (tuỳ chọn) kèm lý do → sale sửa lại nếu cần rồi gửi: hỏi lại NCC (NCC báo giá cho SL / mã
mới trên trang NCC) hoặc — khi không cần NCC báo giá (VD chỉ giảm SL) — gửi thẳng thu mua duyệt. Duyệt thì áp vào đơn
thành MỘT phiên bản (hlv.po.revision, có bản chụp trước / sau; NCC đọc trong khung trao đổi đơn — biết đơn bị giảm SL):
- tăng SL: dòng cũ giữ SL (đổi giá nếu có); phần thêm là DÒNG MỚI cùng đơn, nối vào dòng YCMH cũ;
- giảm SL: giảm SL dòng cũ (Odoo trừ vào phiếu nhập đang mở — hlv_purchase_qty_decrease), YCMH giảm theo;
- đổi mã: dòng mã cũ về SL 0 (giữ dòng để còn lịch sử — Odoo không cho xoá dòng đơn đã xác nhận), mã mới là dòng mới +
  dòng YCMH mới trên cùng YCMH.
Phiếu hỏi giá đổi theo (SL mua của NCC, SL cần mua) để bảng so giá khớp với đơn mua.
"""

from odoo import _, fields, models
from odoo.exceptions import UserError

from .price_proposal_utils import same_money
from .purchase_order_line_price import PRICE_WRITE_CTX
from .purchase_order_revision import tax_rate_of
from .vendor_quote_utils import format_vn_number, split_unit_price

QTY_EPS = 1e-6


class PriceProposalLineChange(models.Model):
    _inherit = "hlv.po.price.proposal"

    uom_id = fields.Many2one(related="order_line_id.product_uom", string="ĐVT")
    old_qty = fields.Float(string="SL trên đơn", digits="Product Unit of Measure", readonly=True)
    suggested_qty = fields.Float(string="SL thu mua đề xuất", digits="Product Unit of Measure", readonly=True,
                                 help="0 = thu mua không đổi số lượng.")
    suggested_product_id = fields.Many2one("product.product", string="Mã thu mua đề xuất", readonly=True)
    # Cái sale chốt gửi đi (sửa lại từ đề xuất của thu mua): 0 / trống = giữ như trên đơn.
    new_qty = fields.Float(string="SL mới", digits="Product Unit of Measure", readonly=True)
    new_product_id = fields.Many2one("product.product", string="Mã mới", readonly=True)
    needs_vendor = fields.Boolean(string="Cần NCC báo giá lại", default=True, readonly=True)
    new_quote_line_id = fields.Many2one("hlv.vendor.quote.line", string="Dòng báo giá mã mới", readonly=True,
                                        ondelete="set null")
    added_order_line_id = fields.Many2one("purchase.order.line", string="Dòng đơn mua thêm", readonly=True,
                                          ondelete="set null")

    # ------------------------------------------------------------------ đọc
    def _target_product(self):
        return self.new_product_id or self.product_id

    def _target_qty(self):
        return self.new_qty or self.old_qty

    def _product_changed(self):
        return bool(self.new_product_id) and self.new_product_id != self.product_id

    def _qty_changed(self):
        return bool(self.new_qty) and abs(self.new_qty - self.old_qty) > QTY_EPS

    def _has_line_change(self):
        """Có đổi SL / mã (không chỉ giá)."""
        return self._product_changed() or self._qty_changed()

    def _target_quote_line(self):
        """Dòng báo giá NCC báo giá cho cái sẽ mua: dòng mã mới khi đổi mã, không thì dòng cũ."""
        return self.new_quote_line_id if self._product_changed() else self.quote_line_id

    def _change_text(self):
        """"SL 1 → 2 Cái", "mã A → B" — "" khi chỉ đổi giá. Dùng trong tin gửi NCC / thu mua / sale."""
        parts = []
        if self._product_changed():
            parts.append(_("mã %(old)s → %(new)s", old=self.product_id.display_name, new=self.new_product_id.display_name))
        if self._qty_changed():
            parts.append(_("SL %(old)s → %(new)s %(uom)s", old=format_vn_number(self.old_qty),
                           new=format_vn_number(self.new_qty), uom=self.uom_id.name or ""))
        return "; ".join(parts)

    # ------------------------------------------------------------------ sale chốt SL / mã
    def _set_line_target(self, qty, product):
        """Sale chốt SL / mã sẽ hỏi NCC hoặc gửi duyệt (sửa lại đề xuất của thu mua nếu cần). product rỗng = giữ mã.
        Lỗi: SL ≤ 0; giảm dưới SL kho đã nhận; đổi mã khi kho đã nhận mã cũ."""
        self.ensure_one()
        po_line = self.order_line_id.sudo()
        product = product or self.product_id
        if qty <= QTY_EPS:
            raise UserError(_("Nhập số lượng lớn hơn 0."))
        changed = product != self.product_id
        if changed and po_line.qty_received:
            raise UserError(_("%(product)s đã nhận kho %(qty)s — không đổi mã được nữa, chỉ đổi giá / số lượng.",
                              product=self.product_id.display_name, qty=format_vn_number(po_line.qty_received)))
        if not changed and qty < po_line.qty_received - QTY_EPS:
            raise UserError(_("Kho đã nhận %s — không giảm dưới số đó.", format_vn_number(po_line.qty_received)))
        self.sudo().write({
            "new_qty": qty if abs(qty - self.old_qty) > QTY_EPS else 0.0,
            "new_product_id": product.id if changed else False,
        })

    def _prepare_target_quote_line(self):
        """Đổi mã: dòng báo giá của NCC của đơn cho mã mới — món mới trên phiếu (SL cần mua 0: phần này do đề xuất lo,
        duyệt xong mới cộng, để phiếu không báo thiếu trong lúc chờ) + dòng trên CHÍNH báo giá NCC đó. Báo giá phải mở
        trước (vendor_quote_requote) mới thêm dòng được. Không đổi mã → dòng cũ."""
        self.ensure_one()
        stale = self.new_quote_line_id
        if stale and (not self._product_changed() or stale.product_id != self.new_product_id):
            # Lần gửi trước đổi sang mã khác: thu hồi dòng đó trên báo giá NCC.
            self._drop_new_quote_line()
            self.sudo().new_quote_line_id = False
        if not self._product_changed():
            return self.quote_line_id
        product = self.new_product_id
        inquiry = self.inquiry_id.sudo()
        quote = self.quote_line_id.quote_id.sudo()
        inquiry_line = inquiry.line_ids.filtered(lambda l: l.product_id == product)[:1]
        if not inquiry_line:
            inquiry_line = self.env["hlv.vendor.inquiry.line"].sudo().create({
                "inquiry_id": inquiry.id, "product_id": product.id, "name": product.display_name,
                "product_qty": self._target_qty(), "product_uom_id": (product.uom_po_id or product.uom_id).id,
                "need_qty": 0.0, "sequence": max(inquiry.line_ids.mapped("sequence") or [0]) + 1,
            })
        quote._hlv_open_quote()
        quote_line = quote.line_ids.filtered(lambda l: l.inquiry_line_id == inquiry_line)[:1]
        if quote_line.withdrawn:
            quote_line.withdrawn = False
        elif not quote_line:
            quote_line = quote.action_add_inquiry_lines(inquiry_line)[:1]
        self.sudo().new_quote_line_id = quote_line.id
        return quote_line

    def _drop_new_quote_line(self):
        """Đề xuất đổi mã kết thúc mà không áp (giữ giá / huỷ): thu hồi dòng mã mới trên báo giá NCC — NCC khỏi báo nữa,
        bảng so giá không còn ô của nó. Món mới trên phiếu giữ lại (sale có thể còn muốn hỏi NCC khác)."""
        line = self.sudo().new_quote_line_id
        if line and not line.selected:
            line.withdrawn = True

    # ------------------------------------------------------------------ thu mua duyệt
    def _apply_line_change(self):
        """Áp giá / SL / mã vào đơn mua thành một phiên bản đã duyệt. Trả phiên bản (rỗng nếu không đổi gì)."""
        self.ensure_one()
        order = self.purchase_order_id.sudo()
        pending = order._hlv_revision_pending()
        if pending:
            raise UserError(_("Đơn %(order)s đang có yêu cầu NCC số %(n)s chờ duyệt — xử lý yêu cầu đó trước.",
                              order=order.name, n=pending.number))
        line = self.order_line_id.sudo()
        tax = tax_rate_of(line)
        new_unit = line.price_unit
        if not same_money(self.new_price_incl, self.old_price_incl):
            new_unit = split_unit_price(self.new_price_incl, tax)[0] or line.price_unit
        locked = order.state == "done"
        if locked:
            order.button_unlock()
        before = order._hlv_snapshot()
        changes = self._apply_to_order(line, new_unit)
        after = order._hlv_snapshot()
        if locked:
            order.button_done()
        return order._hlv_record_proposal_revision(changes, before, after, self)

    def _apply_to_order(self, line, new_unit):
        """Ghi lên đơn + YCMH + phiếu. Trả [(dòng đơn, SL cũ, SL mới, đơn giá cũ, đơn giá mới)] (chưa VAT)."""
        old_qty, old_unit = line.product_qty, line.price_unit
        # Đổi SL làm Odoo tính lại giá + ngày giao theo bảng giá NCC — ghi kèm giá / ngày đang có trong cùng write.
        write = line.with_context(**{PRICE_WRITE_CTX: True}).write
        if self._product_changed():
            new_line = self._add_order_line(self.new_quote_line_id, self._target_qty(), new_unit, new_request=True)
            write({"product_qty": 0.0, "price_unit": old_unit, "date_planned": line.date_planned})
            self._shift_choice(self.quote_line_id, -old_qty)
            return [(line, old_qty, 0.0, old_unit, old_unit), (new_line, 0.0, new_line.product_qty, new_unit, new_unit)]
        target = self._target_qty()
        kept = min(old_qty, target)
        vals = {"price_unit": new_unit}
        if kept < old_qty - QTY_EPS:
            vals.update(product_qty=kept, date_planned=line.date_planned)
        write(vals)
        result = [(line, old_qty, kept, old_unit, new_unit)]
        delta = target - old_qty
        if abs(delta) > QTY_EPS:
            self._shift_choice(self.quote_line_id, delta)
        if delta > QTY_EPS:
            new_line = self._add_order_line(self.quote_line_id, delta, new_unit, new_request=False)
            result.append((new_line, 0.0, delta, new_unit, new_unit))
        return result

    def _shift_choice(self, quote_line, delta):
        """Phiếu + YCMH theo đơn: SL mua của NCC (chosen_qty), dòng YCMH của NCC và SL cần mua của món đổi delta.
        Dòng YCMH về 0 thì huỷ. SL cần mua: tăng thì không dưới tổng đã chia (sale có thể đã cộng SL trên phiếu từ
        trước — không cộng hai lần); giảm thì trừ đúng phần giảm, giữ phần thiếu sẵn có của món."""
        quote_line = quote_line.sudo()
        if quote_line._hlv_live_request_lines():
            quote_line._hlv_resize_request_lines(delta)
        chosen = max(0.0, quote_line.chosen_qty + delta)
        quote_line.write({"chosen_qty": chosen, "selected": chosen > QTY_EPS})
        empty = quote_line._hlv_live_request_lines().filtered(lambda l: l.product_qty <= QTY_EPS)
        if empty:
            empty.do_cancel()
        inquiry_line = quote_line.inquiry_line_id.sudo()
        total = inquiry_line._hlv_chosen_total()
        need = max(inquiry_line.need_qty, total) if delta > 0 else max(total, inquiry_line.need_qty + delta)
        vals = {"need_qty": need}
        if need > inquiry_line.product_qty + QTY_EPS:
            vals["product_qty"] = need
        inquiry_line.write(vals)

    def _add_order_line(self, quote_line, qty, unit, new_request):
        """Thêm dòng mới vào đơn cho quote_line (SL qty, đơn giá chưa VAT unit, cùng thuế / ngày giao với dòng cũ), nối
        dòng YCMH như wizard Tạo RFQ (purchase_request_lines + allocation). new_request: tạo dòng YCMH mới trên cùng YCMH
        (đổi mã); không thì nối dòng YCMH của NCC (đã cộng SL ở _shift_choice)."""
        quote_line = quote_line.sudo()
        old = self.order_line_id.sudo()
        if new_request:
            request_line = self.env["purchase.request.line"].sudo().create(dict(
                quote_line._request_line_actual_vals(), **quote_line._request_line_proposal_vals(),
                request_id=old.purchase_request_lines[:1].request_id.id, product_id=quote_line.product_id.id,
                name=quote_line._hlv_product_label(), product_uom_id=quote_line.product_uom_id.id, product_qty=qty,
            ))
            quote_line.write({"request_line_id": request_line.id, "selected": True, "chosen_qty": qty})
            inquiry_line = quote_line.inquiry_line_id.sudo()
            inquiry_line.need_qty = max(inquiry_line.need_qty, inquiry_line._hlv_chosen_total())
        else:
            live = quote_line._hlv_live_request_lines()
            # Dòng còn phần chưa lên đơn = dòng vừa được cộng SL ở _shift_choice (phần giao ngay hoặc phần hẹn).
            open_part = live.filtered(lambda l: l.product_qty - l.purchased_qty > QTY_EPS)
            request_line = open_part[:1] or (live & quote_line.request_line_id.sudo()) or live[:1]
        product = quote_line.product_id
        uom = request_line.product_uom_id or product.uom_po_id or product.uom_id
        po_line = self.env["purchase.order.line"].sudo().with_context(**{PRICE_WRITE_CTX: True}).create({
            "order_id": old.order_id.id, "product_id": product.id, "name": quote_line._hlv_product_label(),
            "product_qty": qty, "product_uom": uom.id, "price_unit": unit, "taxes_id": [(6, 0, old.taxes_id.ids)],
            "date_planned": old.date_planned, "analytic_distribution": old.analytic_distribution,
            "purchase_request_lines": [(4, request_line.id)] if request_line else [],
        })
        if request_line:
            self.env["purchase.request.allocation"].sudo().create({
                "requested_product_uom_qty": qty, "product_uom_id": request_line.product_uom_id.id,
                "purchase_request_line_id": request_line.id, "purchase_line_id": po_line.id,
            })
            request_line.write({"actual_qty": max(0.0, request_line.product_qty - request_line.purchased_qty)})
        self.sudo().added_order_line_id = po_line.id
        return po_line
