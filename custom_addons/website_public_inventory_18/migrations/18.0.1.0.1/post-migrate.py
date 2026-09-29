"""Hủy các phiếu giữ hàng mồ côi: yêu cầu đã rời trạng thái "Đang giữ" (bị hủy do kho Hủy dự
trữ / xóa dòng / rút hàng) nhưng phiếu kho vẫn còn mở và vẫn khóa hàng — trước bản này, các
con đường đó chỉ đổi trạng thái yêu cầu mà không hủy phiếu."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    live_picking_ids = env["stock.hold.request"].search(
        [("state", "=", "approved")]
    ).hold_picking_id.ids
    dead = env["stock.picking"].search([
        ("is_stock_hold_picking", "=", True),
        ("state", "not in", ("done", "cancel")),
        ("id", "not in", live_picking_ids),
    ])
    if not dead:
        return
    _logger.info("Hủy %s phiếu giữ hàng mồ côi: %s", len(dead), ", ".join(dead.mapped("name")))
    dead.with_context(_skip_hold_unreserve_notify=True, skip_cancel_activity=True).action_cancel()
