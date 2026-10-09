from odoo import models
from odoo.tools import float_compare


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    def _prepare_stock_move_vals(self, picking, price_unit, product_uom_qty, product_uom):
        """Move âm (giảm SL dòng) mang khoá gộp của move nhận còn mở để Odoo trừ thẳng vào đó.

        Core tạo move âm từ cấu hình đơn (kệ mặc định của loại phiếu nhập, date_planned của dòng).
        Phiếu nhập mà kho đã chọn kệ khác / đổi hạn thì lệch khoá, move âm không trừ được và bị
        đảo thành phiếu trả NCC (loại OUT) cho hàng chưa hề nhận — VD DMH23661 → KBC/OUT/13928.
        """
        vals = super()._prepare_stock_move_vals(picking, price_unit, product_uom_qty, product_uom)
        if float_compare(product_uom_qty, 0.0, precision_rounding=product_uom.rounding) < 0:
            receipt = self._open_receipt_move(picking)
            if receipt:
                vals.update(receipt._negative_merge_key_vals())
        return vals

    def _open_receipt_move(self, picking):
        """Move nhận còn mở của dòng trong `picking` — chỉ phiếu này được core xét khi trừ move âm.

        Lấy move có SL lớn nhất để trừ trọn được nhiều nhất; không có thì trả recordset rỗng.
        """
        receipts = self.move_ids.filtered(
            lambda m: m.picking_id == picking
            and m.state not in ("draft", "done", "cancel")
            and m.product_uom_qty > 0
            and not m._is_purchase_return()
        )
        return receipts.sorted("product_uom_qty", reverse=True)[:1]
