import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Giới hạn số lô xử lý trong migration (mỗi lô gọi thêm 1 API MISA/phiếu đại diện) — tránh
# migration chạy quá lâu/timeout nếu dữ liệu quá nhiều; phần còn sót (nếu có) xử lý tiếp bằng
# nút "Sửa gộp sai" trên dashboard (gọi lại đúng stock.picking.repair_misa_invoice_grouped_orders()).
MAX_BATCHES = 10
BATCH_SIZE = 100


def migrate(cr, version):
    """Sửa lại các phiếu 'ăn theo' bị gán SAI bởi phiên bản CŨ của
    _misa_invoice_discover_grouped_orders (chạy trong migration 1.4 và các lần cron sau đó):
    phiên bản cũ chỉ cần order_code của phiếu KHÁC xuất hiện trong đề nghị xuất HĐ là ép NGUYÊN
    phiếu đó về đã xuất HĐ (amount=0), dù đề nghị chỉ phủ đúng 1 PHẦN giá trị/sản phẩm của phiếu
    đó. Case thật đã gặp: phiếu KBC/OUT/11002 xuất hóa đơn CHUNG có nhắc đơn hàng của phiếu
    KBC/OUT/11016, nhưng đề nghị chỉ phủ 1/3 sản phẩm của KBC/OUT/11016 (4.497.000đ trên tổng
    23.553.720đ thực xuất) — phần còn lại (~19M) bị mất dấu vì bị ép về 0.

    Phiên bản mới (models/stock_picking.py::_misa_invoice_discover_grouped_orders) đã sửa: chỉ
    tự động gán 'ăn theo' khi giá trị dòng hàng (đọc từ get_invoice_request_lines, có VAT) khớp
    ĐỦ 100% với misa_invoice_net_actual_amount của phiếu đó; nếu không khớp đủ thì chỉ ghi chú
    cảnh báo, KHÔNG đụng vào state. Migration này quét lại các phiếu đại diện ĐÃ có phiếu ăn
    theo từ trước, và trả các phiếu ăn theo không khớp đủ về 'Chưa kiểm tra' để đối soát lại
    đúng bằng logic mới."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Picking = env['stock.picking'].sudo()

    total_checked = 0
    total_reverted = 0
    for _i in range(MAX_BATCHES):
        result = Picking.repair_misa_invoice_grouped_orders(limit=BATCH_SIZE)
        total_checked += result['checked']
        total_reverted += result['reverted']
        if result['checked'] < BATCH_SIZE:
            break

    _logger.info(
        "✅ [MISA GROUP REPAIR] Backfill hoàn tất: đã kiểm tra %s phiếu đại diện, sửa lại %s phiếu "
        "ăn theo bị gán sai trước đây (nếu còn sót do vượt quá %s lô, dùng nút 'Sửa gộp sai' trên "
        "dashboard để quét tiếp).",
        total_checked, total_reverted, MAX_BATCHES,
    )
