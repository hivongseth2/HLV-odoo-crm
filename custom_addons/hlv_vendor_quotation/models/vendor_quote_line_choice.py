# -*- coding: utf-8 -*-
"""Sale chọn NCC cho sản phẩm của phiếu hỏi giá — một sản phẩm chọn được NHIỀU NCC, mỗi NCC một
"SL mua" (chosen_qty). Mỗi NCC lên YCMH thành dòng riêng (request_line_id); NCC thiếu hàng có hẹn
ngày thì thêm dòng YCMH phần hẹn (backorder_request_line_id, "Ngày cần" = ngày hẹn).

Khác action_select / action_unselect (vendor_quote_line.py): luồng thu mua hỏi giá từ YCMH, một NCC
cho một dòng YCMH có sẵn.
"""

from datetime import timedelta

from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .allocation_utils import apply_qty_delta, buy_qty_error, default_buy_qty, split_buy_qty, supply_cap
from .vendor_quote_utils import format_vn_number


class VendorQuoteLineChoice(models.Model):
    _inherit = "hlv.vendor.quote.line"

    chosen_qty = fields.Float(
        string="SL mua", digits="Product Unit of Measure", copy=False, readonly=True,
        help="Sale chọn NCC này cho sản phẩm: số lượng mua của NCC này (một sản phẩm chia được nhiều NCC).",
    )
    backorder_request_line_id = fields.Many2one(
        "purchase.request.line", string="Dòng YCMH phần hẹn", readonly=True, copy=False, index=True,
        ondelete="set null", help="NCC thiếu hàng, hẹn giao phần còn lại: dòng YCMH riêng theo ngày hẹn.",
    )

    # ------------------------------------------------------------------ đọc
    def _hlv_own_request_lines(self):
        """Dòng YCMH của chính NCC này (phần giao ngay + phần hẹn), kể cả đã huỷ / YCMH bị từ chối."""
        return self.request_line_id | self.backorder_request_line_id

    def _hlv_live_request_lines(self):
        """Dòng YCMH còn hiệu lực của NCC này: dòng chưa huỷ, YCMH không bị từ chối. Đọc bằng sudo —
        sale chỉ có quyền đọc hạn chế trên YCMH."""
        return self._hlv_own_request_lines().sudo().filtered(
            lambda l: not l.cancelled and l.request_id.state != "rejected"
        )

    def _hlv_ordered_qty(self):
        """Phần SL mua của NCC này đã lên RFQ / đơn mua (cộng các dòng YCMH còn hiệu lực)."""
        return sum(self._hlv_live_request_lines().mapped("purchased_qty"))

    def _hlv_needs_request(self):
        """Đã chọn mà chưa nằm trên YCMH còn hiệu lực — nút "Lên / bổ sung YCMH" đưa lên."""
        self.ensure_one()
        return self.selected and not self._hlv_live_request_lines()

    def _hlv_cap(self):
        return supply_cap(self.available_qty, self.no_more)

    def _hlv_product_label(self):
        return self.inquiry_line_id.name or self.product_id.display_name

    # ------------------------------------------------------------------ sale chọn / bỏ chọn / đổi SL
    def _hlv_check_choosable(self):
        inquiry_line = self.inquiry_line_id
        if not inquiry_line:
            raise UserError(_("Dòng báo giá này không thuộc phiếu hỏi giá nào."))
        if inquiry_line.inquiry_id.state in ("cancel", "closed"):
            raise UserError(_(
                "Phiếu %s đã đóng — lập phiếu mới, giá còn hiệu lực sẽ được dùng lại.", inquiry_line.inquiry_id.name,
            ))
        if self.unavailable or not self.price_unit:
            raise UserError(_("NCC chưa báo giá cho mặt hàng này."))

    def action_choose(self, qty=None):
        """Sale chọn thêm NCC này cho sản phẩm. qty: SL mua; None = điền sẵn phần còn thiếu
        (default_buy_qty). Sản phẩm đã chia đủ mà bấm NCC khác = ĐỔI NCC: nhả các NCC chưa lên đơn
        mua (huỷ dòng YCMH của họ nếu có) rồi chọn NCC này — như chọn một NCC trước đây.
        Đã chọn rồi: chỉ đổi SL (action_set_buy_qty)."""
        self.ensure_one()
        self._hlv_check_choosable()
        if self.selected:
            return self.action_set_buy_qty(qty) if qty is not None else True
        inquiry_line = self.inquiry_line_id
        if inquiry_line.locked:
            raise UserError(_(
                "%s đã lên đơn mua đủ số lượng cần mua. NCC giao thiếu: giảm SL mua của NCC đó xuống đúng số "
                "giao được (thu mua sửa dòng đơn mua trước), phần còn thiếu sẽ mở ra để chọn NCC khác.",
                self._hlv_product_label(),
            ))
        if qty is None:
            qty = self._hlv_default_qty()
            if not qty:
                freed = inquiry_line.chosen_line_ids.filtered(lambda l: not l._hlv_ordered_qty())
                freed._hlv_release(_("Sale đổi sang NCC %s", self.partner_id.commercial_partner_id.display_name))
                qty = self._hlv_default_qty()
            if not qty:
                raise UserError(_(
                    "%s đã chia đủ cho NCC đã lên đơn mua — giảm SL mua của NCC đó trước.", self._hlv_product_label(),
                ))
        self._hlv_check_qty(qty, 0.0)
        self.write({"selected": True, "chosen_qty": qty})
        return True

    def _hlv_default_qty(self):
        inquiry_line = self.inquiry_line_id
        others = sum((inquiry_line.chosen_line_ids - self).mapped("chosen_qty"))
        return default_buy_qty(inquiry_line.need_qty, others, self.available_qty, self.no_more)

    def _hlv_check_qty(self, qty, ordered):
        error = buy_qty_error(qty, ordered, self._hlv_cap())
        if error:
            raise UserError(_("%(product)s — %(vendor)s: %(error)s.", product=self._hlv_product_label(),
                              vendor=self.partner_id.commercial_partner_id.display_name, error=error))

    def action_set_buy_qty(self, qty):
        """Sale đổi SL mua của NCC đã chọn. Đã lên YCMH thì sửa luôn dòng YCMH (theo độ lệch — dòng có
        thể gộp hàng phiếu khác), không giảm dưới phần đã lên đơn mua."""
        self.ensure_one()
        self._hlv_check_choosable()
        if not self.selected:
            raise UserError(_("Chưa chọn NCC này — bấm vào giá để chọn."))
        self._hlv_check_qty(qty, self._hlv_ordered_qty())
        if qty != self.chosen_qty and self._hlv_live_request_lines():
            self._hlv_resize_request_lines(qty - self.chosen_qty)
        self.chosen_qty = qty
        return True

    def action_unchoose(self):
        """Sale bỏ chọn NCC. Đã lên đơn mua một phần thì không bỏ được (giảm SL mua xuống phần đã đặt);
        đã lên YCMH (chưa đặt) thì huỷ dòng YCMH của NCC này."""
        for line in self.filtered("selected"):
            ordered = line._hlv_ordered_qty()
            if ordered:
                raise UserError(_(
                    "%(product)s — %(vendor)s đã lên đơn mua %(qty)s: không bỏ chọn được, chỉ giảm SL mua xuống số đó.",
                    product=line._hlv_product_label(), vendor=line.partner_id.commercial_partner_id.display_name,
                    qty=format_vn_number(ordered),
                ))
        self.filtered("selected")._hlv_release(_("Sale bỏ chọn NCC"))
        return True

    def _hlv_release(self, reason):
        """Nhả lựa chọn (chưa lên đơn mua): bỏ chọn, huỷ dòng YCMH còn hiệu lực của NCC này + ghi YCMH.
        Bỏ chọn TRƯỚC khi huỷ dòng: huỷ hết dòng thì OCA tự từ chối YCMH, và hook từ chối
        (_hlv_release_rejected_choices) sẽ báo nhầm "YCMH bị từ chối" nếu dòng còn đang chọn."""
        lines = self.filtered("selected")
        live = {line.id: line._hlv_live_request_lines() for line in lines}
        lines.write({"selected": False, "chosen_qty": 0.0})
        for line in lines:
            if not live[line.id]:
                continue
            live[line.id].do_cancel()
            for request in live[line.id].request_id:
                request.message_post(body=Markup(_("%(reason)s: huỷ dòng <i>%(product)s</i> của <b>%(vendor)s</b> (%(inquiry)s).")) % {
                    "reason": reason, "product": line._hlv_product_label(),
                    "vendor": line.partner_id.commercial_partner_id.display_name,
                    "inquiry": line.inquiry_line_id.inquiry_id.name,
                })

    def _hlv_resize_request_lines(self, delta):
        """Đổi SL các dòng YCMH của NCC này theo delta (apply_qty_delta) + ghi YCMH. Ghi bằng sudo — sale
        chỉ có quyền đọc YCMH. actual_qty = phần còn phải mua: wizard Tạo RFQ ưu tiên actual_qty."""
        live = self._hlv_live_request_lines()
        main = live & self.request_line_id.sudo()
        backorder = live & self.backorder_request_line_id.sudo()
        result = apply_qty_delta(
            main.product_qty, main.purchased_qty, backorder.product_qty, backorder.purchased_qty, delta, bool(backorder),
        )
        if result is None:
            raise UserError(_("%s: không giảm được dưới phần đã lên đơn mua.", self._hlv_product_label()))
        for request_line, qty in ((main, result[0]), (backorder, result[1])):
            if request_line and qty != request_line.product_qty:
                old = request_line.product_qty
                request_line.write({"product_qty": qty, "actual_qty": max(0.0, qty - request_line.purchased_qty)})
                request_line.request_id.message_post(body=Markup(_(
                    "Sale đổi SL mua <i>%(product)s</i> của <b>%(vendor)s</b>: %(old)s → %(new)s (%(inquiry)s)."
                )) % {
                    "product": self._hlv_product_label(), "vendor": self.partner_id.commercial_partner_id.display_name,
                    "old": format_vn_number(old), "new": format_vn_number(qty), "inquiry": self.inquiry_line_id.inquiry_id.name,
                })

    # ------------------------------------------------------------------ lên YCMH
    def _hlv_request_parts(self):
        """Dòng YCMH cần tạo cho NCC này: [(vals, là phần hẹn)] — tách phần giao ngay / phần hẹn
        (split_buy_qty). Kèm NCC + giá cho wizard Tạo RFQ (actual_*) và cột "sale đề xuất"."""
        self.ensure_one()
        base = dict(
            {
                "product_id": self.product_id.id,
                "name": self._hlv_product_label(),
                "product_uom_id": self.product_uom_id.id,
            },
            **self._request_line_actual_vals(),
            **self._request_line_proposal_vals(),
        )
        parts = []
        for qty, backorder_date in split_buy_qty(self.chosen_qty, self.available_qty, self.backorder_date, self.no_more):
            vals = dict(base, product_qty=qty)
            if backorder_date:
                vals.update(date_required=backorder_date, hlv_backorder=True)
            elif self.delivery_days:
                vals["date_required"] = self.quote_id._vendor_today() + timedelta(days=self.delivery_days)
            parts.append((vals, bool(backorder_date)))
        return parts

    @api.model
    def _hlv_link_request_lines(self, links):
        """Gắn dòng YCMH vừa tạo / gộp vào dòng báo giá. links: [(dòng báo giá, dòng YCMH, là phần hẹn)].
        Dòng không có phần hẹn thì xoá liên kết phần hẹn cũ (YCMH trước bị từ chối / huỷ)."""
        main, backorder = {}, {}
        for quote_line, request_line, is_backorder in links:
            (backorder if is_backorder else main)[quote_line] = request_line
        for quote_line in set(main) | set(backorder):
            quote_line.write({
                "request_line_id": main.get(quote_line, quote_line.request_line_id.browse()).id or False,
                "backorder_request_line_id": backorder.get(quote_line, quote_line.request_line_id.browse()).id or False,
            })
