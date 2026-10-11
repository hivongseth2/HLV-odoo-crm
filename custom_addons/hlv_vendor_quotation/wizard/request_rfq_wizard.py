# -*- coding: utf-8 -*-
"""Wizard "Tạo RFQ" từ dòng YCMH (OCA purchase_request) khi có dòng phần NCC hẹn giao:

- tự bật "Chỉ gộp nếu trùng Ngày dự kiến" — không thì phần giao ngay và phần hẹn (cùng sản phẩm, cùng NCC)
  bị gộp thành MỘT dòng đơn mua, mất ngày hẹn;
- "Tách đơn mua riêng cho phần NCC hẹn giao": mặc định theo lựa chọn của sale lúc lên YCMH
  (purchase.request.line.hlv_separate_po), thu mua đổi được. Bật thì phần hẹn ra đơn mua riêng.
"""

from odoo import api, fields, models


class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order"

    hlv_has_backorder = fields.Boolean(compute="_compute_hlv_has_backorder")
    hlv_split_backorder = fields.Boolean(
        string="Tách đơn mua riêng cho phần NCC hẹn giao",
        help="Bật: hàng NCC hẹn giao sau ra đơn mua riêng (phiếu nhập riêng). Tắt: chung đơn với hàng có sẵn, "
             "mỗi dòng giữ ngày dự kiến riêng. Mặc định theo lựa chọn của sale khi lên YCMH.",
    )

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
        """Tách phần hẹn: chạy wizard gốc hai lượt — hàng có sẵn trên wizard này, phần hẹn trên một wizard thứ
        hai — mỗi lượt wizard gốc gom mỗi NCC một đơn, nên phần hẹn ra đơn riêng. Không chép lại cách gom đơn
        của OCA. Đơn có sẵn chọn ở "Đơn mua hàng có sẵn" chỉ nhận hàng có sẵn."""
        self.ensure_one()
        backorder_items = self.item_ids.filtered(lambda item: item.line_id.hlv_backorder)
        if not self.hlv_split_backorder or not backorder_items or backorder_items == self.item_ids:
            return super().make_purchase_order()
        # item_ids=[] + bỏ active_ids: wizard mới không tự lấy lại mọi dòng YCMH từ ngữ cảnh (default_get).
        later = self.with_context(active_ids=[], active_model=False).create({
            "item_ids": [], "supplier_id": self.supplier_id.id, "sync_data_planned": self.sync_data_planned,
        })
        backorder_items.write({"wiz_id": later.id})
        first = super().make_purchase_order()
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
