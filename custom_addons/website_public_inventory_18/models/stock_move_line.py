# -*- coding: utf-8 -*-
import logging

from odoo import models

from .stock_picking import _dispatch_unreserve_notifications

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    def unlink(self):
        """Kho có thể nhả reservation bằng cách xóa thẳng dòng move line (icon thùng rác trong
        popup "Điều chuyển tồn kho" / "Chi tiết hoạt động"), KHÔNG qua nút "Hủy dự trữ" nào cả —
        con đường này không đi qua stock.picking.do_unreserve(), nên nếu không bắt riêng ở đây,
        phiếu giữ hàng / phiếu PICK của đơn bán bị mất reservation theo cách này sẽ không được
        đồng bộ trạng thái/cảnh báo gì hết.

        context _skip_hold_unreserve_notify: do_unreserve() (module này) tự set cờ này khi gọi
        super() để tránh việc unlink() bị gọi lồng bên trong đó bắn thêm 1 lần thông báo trùng.
        """
        if self.env.context.get("_skip_hold_unreserve_notify"):
            return super().unlink()

        affected_pickings = self.mapped("picking_id")
        res = super().unlink()

        if affected_pickings:
            _dispatch_unreserve_notifications(affected_pickings, "delete_move_line")
        return res

    def write(self, vals):
        """Có module khác (vd hlv_priority_stock_reservation, wizard "rút hàng" để nhường cho
        đơn ưu tiên hơn) nhả reservation bằng cách ghi thẳng move_line.quantity GIẢM xuống (kể cả
        về 0) — không unlink(), không đi qua do_unreserve() — nên 2 hook trên hoàn toàn không bắt
        được con đường này. Phát hiện bằng cách so sánh quantity trước/sau write(): nếu giảm và
        phiếu chưa done/cancel, coi như 1 lần "rút bớt reservation" cần cảnh báo.

        Chỉ so sánh khi thực sự có 'quantity' trong vals để tránh overhead so sánh không cần
        thiết cho mọi write() khác (write trên move line diễn ra rất thường xuyên)."""
        skip = self.env.context.get("_skip_hold_unreserve_notify")
        before_by_id = {}
        if "quantity" in vals and not skip:
            before_by_id = {ml.id: ml.quantity for ml in self}

        res = super().write(vals)

        if before_by_id:
            reduced = self.filtered(
                lambda ml: ml.id in before_by_id and ml.quantity < before_by_id[ml.id]
            )
            affected_pickings = reduced.mapped("picking_id")
            if affected_pickings:
                _dispatch_unreserve_notifications(affected_pickings, "quantity_reduced")
        return res
