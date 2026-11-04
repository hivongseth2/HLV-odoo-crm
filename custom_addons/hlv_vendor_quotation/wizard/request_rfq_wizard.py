# -*- coding: utf-8 -*-
"""Wizard "Tạo RFQ" từ dòng YCMH (OCA purchase_request) khi có dòng phần NCC hẹn giao:

- tự bật "Chỉ gộp nếu trùng Ngày dự kiến" — không thì phần giao ngay và phần hẹn (cùng sản phẩm, cùng NCC)
  bị gộp thành MỘT dòng đơn mua, mất ngày hẹn;
- "Tách đơn mua riêng cho phần NCC hẹn giao": mặc định theo lựa chọn của sale lúc lên YCMH
  (purchase.request.line.hlv_separate_po), thu mua đổi được. Bật thì phần hẹn ra đơn mua riêng.

Dòng YCMH gắn với phiếu hỏi giá: giá và số lượng trong wizard là của phiếu hỏi giá, thu mua không sửa được
(_hlv_check_locked_items).
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

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

    @api.model
    def _prepare_item(self, line):
        """Dòng gắn với phiếu hỏi giá: SL lên đơn = đúng phần còn phải mua của dòng YCMH (sale chốt trên phiếu). actual_qty
        cũ trên dòng có thể là số của lần Tạo RFQ trước (misa_purchase_request_sync ghi lại) — không dùng."""
        res = super()._prepare_item(line)
        if line.hlv_price_locked:
            res["actual_qty"] = line._hlv_remaining_qty()
        return res

    def make_purchase_order(self):
        # Dòng đơn mua lên từ hỏi giá bị khoá (purchase_order_line_price): wizard ghi giá / SL đã chốt trên YCMH (đặt SL,
        # gộp vào dòng có sẵn) là đường được phép — nên giá / SL trong wizard phải đúng của phiếu hỏi giá.
        self._hlv_check_locked_items()
        return self.with_context(**{PRICE_WRITE_CTX: True})._hlv_make_purchase_order()

    def _hlv_check_locked_items(self):
        """Dòng YCMH gắn với phiếu hỏi giá: giá trong wizard phải là giá sale chọn trên trang hỏi giá (cột "sale đề xuất"
        của dòng YCMH — vendor_quote_line._request_line_proposal_vals), so theo giá sau VAT; số lượng phải là phần còn
        phải mua của dòng YCMH. Thu mua muốn giá khác thì tạo RFQ rồi "Đề xuất giá" trên dòng đơn mua; muốn SL khác thì
        sale bổ sung / giảm trên phiếu hỏi giá."""
        # Giá / thuế wizard thật sự dùng (misa_purchase_request_sync): đơn giá trống thì lấy giá sale đề xuất, thuế
        # chọn từ danh sách ưu tiên hơn % gõ tay.
        changed = self.item_ids.filtered(lambda item: item.hlv_price_locked and not same_price_incl(
            item.actual_price_unit or item.misa_price_before_tax,
            item.actual_tax_id.amount if item.actual_tax_id else item.actual_tax_rate, item.actual_discount_rate,
            item.line_id.misa_price_before_tax, item.line_id.misa_tax_rate, item.line_id.misa_discount_rate,
        ))
        if changed:
            raise UserError(_(
                "%s gắn với phiếu hỏi giá — giữ đúng giá sale đã chọn. Muốn giá khác: tạo RFQ rồi bấm \"Đề xuất giá\" "
                "trên dòng đơn mua để sale hỏi lại NCC.",
                ", ".join(changed.mapped(lambda item: item.product_id.display_name)),
            ))
        changed = self.item_ids.filtered(lambda item: item.hlv_price_locked and not item._hlv_qty_as_requested())
        if changed:
            raise UserError(_(
                "%s gắn với phiếu hỏi giá — số lượng phải đúng phần còn phải mua trên YCMH. Muốn mua khác số đó: sale "
                "đổi SL mua / bổ sung trên phiếu hỏi giá.",
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

    # Dòng YCMH gắn với phiếu hỏi giá: ô giá / thuế / chiết khấu / số lượng / sản phẩm trong wizard chỉ xem (kiểm lại ở
    # PurchaseRequestLineMakePurchaseOrder._hlv_check_locked_items).
    hlv_price_locked = fields.Boolean(related="line_id.hlv_price_locked", string="Giá theo hỏi giá")

    def _hlv_qty_as_requested(self):
        """Đúng sản phẩm và SL wizard sẽ lên đơn (actual_qty, trống thì product_qty — như misa_purchase_request_sync) bằng
        phần còn phải mua của dòng YCMH, quy về ĐVT của dòng YCMH."""
        self.ensure_one()
        line = self.line_id
        if self.product_id != line.product_id:
            return False
        qty = self.actual_qty or self.product_qty or 0.0
        if self.product_uom_id and self.product_uom_id != line.product_uom_id:
            qty = self.product_uom_id._compute_quantity(qty, line.product_uom_id)
        rounding = line.product_uom_id.rounding or 0.001
        return float_compare(qty, line._hlv_remaining_qty(), precision_rounding=rounding) == 0
