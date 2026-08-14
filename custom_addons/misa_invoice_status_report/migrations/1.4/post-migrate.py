import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Giới hạn số lô xử lý trong migration (mỗi lô gọi thêm 1 API MISA/phiếu) — tránh migration
# chạy quá lâu/timeout nếu dữ liệu quá nhiều; phần còn sót (nếu có) xử lý tiếp bằng nút "Quét
# đơn xuất kèm" trên dashboard (gọi lại đúng stock.picking.scan_misa_invoice_grouped_orders()).
MAX_BATCHES = 10
BATCH_SIZE = 100


def migrate(cr, version):
    """Backfill: các phiếu ĐÃ 'invoiced' từ TRƯỚC KHI có tính năng "quét đơn xuất kèm" (đọc
    chi tiết dòng hàng đề nghị xuất HĐ để tìm đơn hàng KHÁC được xuất hóa đơn CHUNG mà MISA
    không tự báo qua master_refno) sẽ không tự có misa_invoice_group_checked — quét lại 1 lần
    cho dữ liệu cũ. Ví dụ thật đã gặp: phiếu KBC/OUT/11521 xuất hóa đơn gộp chung cho cả đơn
    hàng của phiếu KBC/OUT/11408, nhưng KBC/OUT/11408 bị treo mãi ở 'Chưa có đề nghị' vì không
    có cơ chế nào trước đây phát hiện được việc gộp này."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Picking = env['stock.picking'].sudo()

    total_checked = 0
    total_discovered = 0
    for _i in range(MAX_BATCHES):
        result = Picking.scan_misa_invoice_grouped_orders(limit=BATCH_SIZE)
        total_checked += result['checked']
        total_discovered += result['discovered']
        if result['checked'] < BATCH_SIZE:
            break

    _logger.info(
        "✅ [MISA GROUP DISCOVER] Backfill hoàn tất: đã quét %s phiếu, phát hiện thêm %s phiếu xuất kèm "
        "(nếu còn sót do vượt quá %s lô, dùng nút 'Quét đơn xuất kèm' trên dashboard để quét tiếp).",
        total_checked, total_discovered, MAX_BATCHES,
    )
