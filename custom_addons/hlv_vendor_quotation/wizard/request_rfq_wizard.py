# -*- coding: utf-8 -*-
"""Wizard "Tạo RFQ" từ dòng YCMH (OCA purchase_request) khi có dòng phần NCC hẹn giao:

- tự bật "Chỉ gộp nếu trùng Ngày dự kiến" — không thì phần giao ngay và phần hẹn (cùng sản phẩm, cùng NCC)
  bị gộp thành MỘT dòng đơn mua, mất ngày hẹn;
- "Tách đơn mua riêng cho phần NCC hẹn giao": mặc định theo lựa chọn của sale lúc lên YCMH
  (purchase.request.line.hlv_separate_po), thu mua đổi được. Bật thì phần hẹn ra đơn mua riêng.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.price_proposal_utils import same_price_incl
from ..models.purchase_order_line_price import PRICE_WRITE_CTX


class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order"

    hlv_has_backorder = fields.Boolean(compute="_compute_hlv_has_backorder")
    hlv_split_backorder = fields.Boolean(
        string="Tách đơn mua riêng cho phần NCC hẹn giao",
        help="Bật: hàng NCC hẹn giao sau ra đơn mua riêng (phiếu nhập riêng). Tắt: chung đơn với hàng có sẵn, "
             "mỗi dòng giữ ngày dự kiến riêng. Mặc định theo lựa chọn của sale khi lên YCMH.",
    )

    hlv_date_wanted = fields.Date(string="Ngày sale muốn nhận hàng", compute="_compute_hlv_date_wanted")

    @api.depends("item_ids.line_id.request_id.hlv_date_wanted")
    def _compute_hlv_date_wanted(self):
        for wizard in self:
            wizard.hlv_date_wanted = wizard.item_ids.line_id._hlv_date_wanted()

    @api.depends("item_ids.line_id.hlv_backorder")
    def _compute_hlv_has_backorder(self):
        for wizard in self:
            wizard.hlv_has_backorder = any(wizard.item_ids.line_id.mapped("hlv_backorder"))

    @api.model
    def get_items(self, request_line_ids):
        """Bỏ dòng YCMH đã huỷ: sale đổi NCC trên trang hỏi giá thì dòng của NCC cũ bị huỷ
        (vendor_quote_line_choice._hlv_release) — wizard gốc không lọc, sẽ lên đơn mua cả hàng đã đổi NCC."""
        lines = self.env["purchase.request.line"].browse(request_line_ids).filtered(lambda line: not line.cancelled)
        return super().get_items(lines.ids)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        backorder = self._hlv_selected_request_lines().filtered("hlv_backorder")
        if "sync_data_planned" in fields_list and backorder:
            res["sync_data_planned"] = True
        if "hlv_split_backorder" in fields_list:
            res["hlv_split_backorder"] = any(backorder.mapped("hlv_separate_po"))
        return res

    def make_purchase_order(self):
        # Dòng đơn mua lên từ hỏi giá bị khoá giá (purchase_order_line_price): wizard ghi giá đã chọn trên YCMH
        # (đặt SL, gộp vào dòng có sẵn) là đường được phép — nên giá trong wizard phải đúng giá đã chọn.
        self._hlv_check_locked_prices()
        return self.with_context(**{PRICE_WRITE_CTX: True})._hlv_make_purchase_order()

    def _hlv_check_locked_prices(self):
        """Dòng YCMH lập từ trang hỏi giá: giá trong wizard phải là giá sale chọn trên trang hỏi giá (cột "sale đề xuất"
        của dòng YCMH — vendor_quote_line._request_line_proposal_vals), so theo giá sau VAT. Thu mua muốn giá khác thì
        tạo RFQ rồi "Đề xuất giá" trên dòng đơn mua."""
        # Giá / thuế wizard thật sự dùng (misa_purchase_request_sync): đơn giá trống thì lấy giá sale đề xuất, thuế
        # chọn từ danh sách ưu tiên hơn % gõ tay.
        changed = self.item_ids.filtered(lambda item: item.hlv_price_locked and not same_price_incl(
            item.actual_price_unit or item.misa_price_before_tax,
            item.actual_tax_id.amount if item.actual_tax_id else item.actual_tax_rate, item.actual_discount_rate,
            item.line_id.misa_price_before_tax, item.line_id.misa_tax_rate, item.line_id.misa_discount_rate,
        ))
        if changed:
            raise UserError(_(
                "%s lên từ trang hỏi giá — giữ đúng giá sale đã chọn. Muốn giá khác: tạo RFQ rồi bấm \"Đề xuất giá\" "
                "trên dòng đơn mua để sale hỏi lại NCC.",
                ", ".join(changed.mapped(lambda item: item.product_id.display_name)),
            ))

    def _hlv_make_purchase_order(self):
        """Tách phần hẹn: chạy wizard gốc hai lượt — hàng có sẵn trên wizard này, phần hẹn trên một wizard thứ
        hai — mỗi lượt wizard gốc gom mỗi NCC một đơn, nên phần hẹn ra đơn riêng. Không chép lại cách gom đơn
        của OCA. Đơn có sẵn chọn ở "Đơn mua hàng có sẵn" chỉ nhận hàng có sẵn."""
        self.ensure_one()
        backorder_items = self.item_ids.filtered(lambda item: item.line_id.hlv_backorder)
        if not self.hlv_split_backorder or not backorder_items or backorder_items == self.item_ids:
            return super(PurchaseRequestLineMakePurchaseOrder, self).make_purchase_order()
        # item_ids=[] + bỏ active_ids: wizard mới không tự lấy lại mọi dòng YCMH từ ngữ cảnh (default_get).
        later = self.with_context(active_ids=[], active_model=False).create({
            "item_ids": [], "supplier_id": self.supplier_id.id, "sync_data_planned": self.sync_data_planned,
        })
        backorder_items.write({"wiz_id": later.id})
        first = super(PurchaseRequestLineMakePurchaseOrder, self).make_purchase_order()
        second = super(PurchaseRequestLineMakePurchaseOrder, later).make_purchase_order()
        order_ids = first["domain"][0][2] + [i for i in second["domain"][0][2] if i not in first["domain"][0][2]]
        return dict(first, domain=[("id", "in", order_ids)])

    @api.model
    def _hlv_selected_request_lines(self):
        """Dòng YCMH wizard đang mở cho — cùng cách OCA đọc context (active_model / active_ids)."""
        context = self.env.context
        ids = context.get("active_ids") or []
        if context.get("active_model") == "purchase.request.line":
            return self.env["purchase.request.line"].browse(ids)
        if context.get("active_model") == "purchase.request":
            return self.env["purchase.request"].browse(ids).line_ids
        return self.env["purchase.request.line"]


class PurchaseRequestLineMakePurchaseOrderItem(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order.item"

    # Dòng YCMH lập từ trang hỏi giá: ô giá / thuế / chiết khấu trong wizard chỉ xem (kiểm lại ở
    # PurchaseRequestLineMakePurchaseOrder._hlv_check_locked_prices).
    hlv_price_locked = fields.Boolean(related="line_id.request_id.hlv_from_quote_page", string="Giá theo hỏi giá")
