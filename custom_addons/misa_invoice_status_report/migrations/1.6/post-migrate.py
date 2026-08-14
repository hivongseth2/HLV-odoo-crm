import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Giới hạn số lô xử lý trong migration (mỗi lô gọi thêm 1 API MISA/phiếu đại diện) — tránh
# migration chạy quá lâu/timeout nếu dữ liệu quá nhiều; phần còn sót (nếu có) xử lý tiếp bằng
# nút "Quét đơn xuất kèm" trên dashboard (gọi lại đúng stock.picking.scan_misa_invoice_grouped_orders()).
MAX_BATCHES = 10
BATCH_SIZE = 100


def migrate(cr, version):
    """_misa_invoice_discover_grouped_orders giờ khớp theo TỪNG DÒNG HÀNG (mã hàng + số lượng,
    misa.invoice.grouped.line/.match) thay vì chỉ so tổng tiền của cả đơn — trước đây, khi 1 đề
    nghị chỉ xuất hóa đơn MỘT PHẦN giá trị của 1 đơn hàng khác (case thật: KBC/OUT/11002 xuất
    hóa đơn chung nhưng chỉ phủ đúng 1/3 sản phẩm của phiếu KBC/OUT/11016), hệ thống chỉ ghi
    chú cảnh báo — KHÔNG lưu lại dữ liệu dòng hàng nào, nên phần ĐÃ khớp không được trừ vào
    "còn thiếu hóa đơn" của phiếu kia.

    Migration này reset misa_invoice_group_checked = False cho MỌI phiếu đại diện đã từng được
    quét (kể cả khi lần quét trước không phát hiện gì sai) để quét lại toàn bộ bằng logic mới —
    qua đó lấp đầy misa.invoice.grouped.line/.match và misa_invoice_grouped_matched_amount cho
    các trường hợp khớp MỘT PHẦN trước đây bị bỏ sót hoàn toàn (không phải lỗi gán SAI như
    migration 1.5 xử lý, mà là dữ liệu CHƯA TỪNG được ghi nhận)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Picking = env['stock.picking'].sudo()

    to_rescan = Picking.search([
        ('picking_type_id.code', '=', 'outgoing'),
        ('misa_invoice_state', '=', 'invoiced'),
        ('misa_invoice_master_picking_id', '=', False),
        ('misa_invoice_request_refid', '!=', False),
        ('misa_invoice_group_checked', '=', True),
    ])
    to_rescan.write({'misa_invoice_group_checked': False})
    _logger.info(
        "✅ [MISA GROUP LINE MATCH] Đã reset misa_invoice_group_checked cho %s phiếu đại diện để quét lại "
        "bằng logic mới (khớp theo dòng hàng).", len(to_rescan),
    )

    total_checked = 0
    total_discovered = 0
    for _i in range(MAX_BATCHES):
        result = Picking.scan_misa_invoice_grouped_orders(limit=BATCH_SIZE)
        total_checked += result['checked']
        total_discovered += result['discovered']
        if result['checked'] < BATCH_SIZE:
            break

    _logger.info(
        "✅ [MISA GROUP LINE MATCH] Backfill hoàn tất: đã quét lại %s phiếu, phát hiện thêm %s phiếu xuất "
        "kèm khớp ĐỦ (nếu còn sót do vượt quá %s lô, dùng nút 'Quét đơn xuất kèm' trên dashboard để quét "
        "tiếp — các trường hợp khớp MỘT PHẦN đã được ghi nhận qua misa.invoice.grouped.line ngay trong "
        "lần quét này, không cần chờ khớp đủ).",
        total_checked, total_discovered, MAX_BATCHES,
    )
