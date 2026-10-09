from odoo import models
from odoo.tools import float_compare, float_is_zero


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    def _create_stock_moves(self, picking):
        """Giảm SL dòng: trừ thẳng vào phần chưa nhận của phiếu nhập đang mở, không để move âm
        đi đường gộp của core.

        Core tạo move âm rồi nhờ _merge_moves trừ vào move nhận. Nhưng _merge_moves gỡ picking_id
        của move âm trước khi so khoá, nên location_dest_id (compute theo picking_id) bị tính lại
        về kệ mặc định của loại phiếu nhập. Phiếu nhập nào kho đã chọn kệ khác thì không bao giờ
        khớp, move âm bị đảo thành phiếu trả NCC (OUT) cho hàng chưa hề nhận
        (VD DMH23714 → KBC/OUT/13965). Chép khoá vào move âm không cứu được vì bị tính lại sau đó.
        """
        moves = super()._create_stock_moves(picking)
        absorbed = moves.browse()
        negatives = moves.filtered(
            lambda m: m.purchase_line_id
            and float_compare(m.product_uom_qty, 0.0, precision_rounding=m.product_uom.rounding) < 0
        )
        for move in negatives:
            if move.purchase_line_id._absorb_into_open_receipts(move, picking):
                absorbed |= move
        absorbed.unlink()
        return moves - absorbed

    def _absorb_into_open_receipts(self, negative_move, picking):
        """Trừ SL của `negative_move` vào các move nhận còn mở của dòng.

        Trả True khi trừ hết (bên gọi xoá move âm); False khi còn dư — move âm được thu nhỏ còn
        phần dư và đi tiếp đường core (thành phiếu trả như cũ).
        """
        self.ensure_one()
        uom = negative_move.product_uom
        remaining = -negative_move.product_uom_qty
        for receipt in self._open_receipt_moves(negative_move.product_id, picking):
            # Phần kho đã đếm (picked) giữ nguyên: giảm nhu cầu dưới SL đã đếm thì kho phải tự xử lý.
            free = receipt.product_uom_qty - (receipt.quantity if receipt.picked else 0.0)
            take = min(remaining, receipt.product_uom._compute_quantity(free, uom))
            if float_compare(take, 0.0, precision_rounding=uom.rounding) <= 0:
                continue
            receipt.product_uom_qty -= uom._compute_quantity(take, receipt.product_uom)
            if float_is_zero(receipt.product_uom_qty, precision_rounding=receipt.product_uom.rounding):
                # Như core khi gộp trừ hết: không lan huỷ sang move đích (phiếu giao của đơn bán).
                receipt._clean_merged()
                receipt._action_cancel()
            remaining -= take
            if float_is_zero(remaining, precision_rounding=uom.rounding):
                return True
        negative_move.product_uom_qty = -remaining
        return False

    def _open_receipt_moves(self, product, picking):
        """Move nhận còn mở của dòng cho `product` (dòng kit có nhiều linh kiện), không gồm move trả.

        Phiếu `picking` (phiếu core chọn) trước, rồi tới move mới nhất; không có thì recordset rỗng.
        """
        receipts = self.move_ids.filtered(
            lambda m: m.product_id == product
            and m.state not in ("draft", "done", "cancel")
            and m.location_dest_id.usage in ("internal", "transit", "customer")
            and not m._is_purchase_return()
            and float_compare(m.product_uom_qty, 0.0, precision_rounding=m.product_uom.rounding) > 0
        )
        return receipts.sorted(lambda m: (m.picking_id != picking, -m.id))
