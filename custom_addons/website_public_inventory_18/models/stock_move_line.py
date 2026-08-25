# -*- coding: utf-8 -*-
import logging

from odoo import models

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

        affected_pickings = self.mapped("picking_id").filtered(
            lambda p: p.state not in ("done", "cancel")
        )
        hold_pickings = affected_pickings.filtered("is_stock_hold_picking")
        sale_pick_pickings = affected_pickings.filtered(
            lambda p: not p.is_stock_hold_picking
            and p.picking_type_id.sequence_code == "PICK"
            and p.sale_id
        )

        res = super().unlink()

        if hold_pickings:
            try:
                hold_pickings._sync_and_notify_hold_pickings_unreserved(reason="delete_move_line")
            except Exception:
                _logger.exception(
                    "Lỗi đồng bộ/cảnh báo phiếu giữ hàng sau khi xóa move line thủ công."
                )
        if sale_pick_pickings:
            try:
                sale_pick_pickings._notify_sale_pick_unreserved(reason="delete_move_line")
            except Exception:
                _logger.exception(
                    "Lỗi gửi cảnh báo phiếu PICK sau khi xóa move line thủ công."
                )
        return res
