import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Backfill 1 LẦN cho toàn bộ phiếu outgoing đã done đang tồn tại TRƯỚC khi có tính năng
    "trừ hàng trả" (misa_invoice_net_actual_amount, misa_invoice_returned_amount) — 2 field
    mới này mặc định = 0.0 cho mọi phiếu cũ (chưa từng qua button_validate với code mới), nếu
    không backfill thì ngay sau khi nâng cấp module, mọi tổng đối soát trên dashboard (vốn đã
    chuyển sang đọc misa_invoice_net_actual_amount thay vì x_studio_tng_tin_sau_thu) sẽ đột
    ngột về gần 0.

    Chạy qua migrations/ (không dùng post_init_hook) vì post_init_hook CHỈ chạy khi cài mới
    module lần đầu — module này đã cài sẵn từ trước, cần cơ chế chạy được khi NÂNG CẤP
    (-u misa_invoice_status_report), đúng việc migrations/<version>/post-migrate.py làm được."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Picking = env['stock.picking'].sudo()
    pickings = Picking.search([
        ('picking_type_id.code', '=', 'outgoing'),
        ('state', '=', 'done'),
    ])
    _logger.info("🔄 [MISA RETURN] Backfill tiền thực xuất ròng cho %s phiếu xuất kho...", len(pickings))
    done = 0
    for picking in pickings:
        try:
            picking._misa_invoice_recompute_net_amount()
            done += 1
        except Exception:
            _logger.exception("❌ [MISA RETURN] Lỗi backfill phiếu %s", picking.name)
    _logger.info("✅ [MISA RETURN] Backfill hoàn tất: %s/%s phiếu.", done, len(pickings))
