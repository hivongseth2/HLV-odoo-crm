import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Bản 1.6 đã lên production TRƯỚC KHI có loạt fix sau cùng của module này (loại trừ phiếu
    đã tự có hóa đơn độc lập khỏi diện "còn trống có thể nhận" trong
    _misa_invoice_discover_grouped_orders, Cơ chế A không còn gán "ăn theo" mù mà giao hẳn cho
    engine khớp dòng hàng quyết định, sửa gán lồng nhau, đối chiếu dòng hàng cho CHÍNH phiếu
    trong nhóm chứ không chỉ các đơn khác...).

    QUAN TRỌNG (bài học thật — migration trước đó từng làm SẬP production): migration chạy
    trong lúc `-u` PHẢI nhanh và an toàn — KHÔNG BAO GIỜ được gọi API bên ngoài (MISA) hàng
    loạt ở đây, vì tùy cách deploy, nó có thể CHẶN CẢ SERVER (không thao tác được) trong lúc
    module đang nâng cấp, có khi hàng chục phút nếu dữ liệu nhiều mà không cách nào xem tiến
    độ. Migration này CHỈ làm 2 việc thuần DB (nhanh, không gọi mạng):
    1. Sửa các phiếu bị gán "ăn theo" LỒNG NHAU (chain 2+ tầng) — chỉ đi theo con trỏ
       master_picking_id đã có sẵn trong DB, không cần hỏi MISA gì cả.
    2. Gộp hóa đơn trùng theo request_refid (dữ liệu đã có sẵn trong DB).

    Các bước CẦN gọi API MISA (quét đơn xuất kèm, sửa gộp sai theo dòng hàng, cập nhật lý do
    lệch) KHÔNG chạy tự động ở đây nữa — sau khi deploy xong, vào dashboard bấm lần lượt "Quét
    đơn xuất kèm" / "Sửa gộp sai" / "Cập nhật lý do lệch" (mỗi nút giờ tự chạy hết toàn bộ danh
    sách trong 1 lần bấm, có thanh tiến độ thấy được ngay trên trình duyệt — không đụng gì tới
    server, chỉ tốn thời gian phiên làm việc của người bấm)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Picking = env['stock.picking'].sudo()

    # 1) Sửa các phiếu bị gán "ăn theo" LỒNG NHAU (chain 2+ tầng) — thuần DB, không gọi MISA.
    total_checked = 0
    total_flattened = 0
    for _i in range(20):
        result = Picking.flatten_misa_invoice_master_chains(limit=500)
        total_checked += result['checked']
        total_flattened += result['flattened']
        if result['checked'] < 500:
            break
    _logger.info(
        "✅ [MISA 1.7] Bước 1/2 hoàn tất: đã kiểm tra %s phiếu, sửa %s phiếu bị gán lồng nhau.",
        total_checked, total_flattened,
    )

    # 2) Gộp hóa đơn trùng (request_refid trùng nhau ở nhiều phiếu 'invoiced' chưa liên kết) —
    # thuần DB (đọc SQL + write), không gọi MISA. Lưới an toàn dự phòng, nay đã flatten cả nhóm
    # thay vì chỉ phần "ungrouped" (xem _misa_invoice_dedupe_request_refid_groups).
    cr.execute("""
        SELECT misa_invoice_request_refid
        FROM stock_picking
        WHERE misa_invoice_state = 'invoiced' AND misa_invoice_request_refid IS NOT NULL
        GROUP BY misa_invoice_request_refid
        HAVING COUNT(*) > 1
    """)
    refids = [row[0] for row in cr.fetchall()]
    try:
        Picking._misa_invoice_dedupe_request_refid_groups(request_refids=refids)
        _logger.info("✅ [MISA 1.7] Bước 2/2 (dedupe) hoàn tất: đã kiểm tra %s mã request_refid trùng.", len(refids))
    except Exception:
        _logger.exception("❌ [MISA 1.7] Lỗi ở bước dedupe.")

    _logger.info(
        "✅ [MISA 1.7] Backfill nhanh (thuần DB) hoàn tất. CÒN CẦN bấm tay trên dashboard (sau khi "
        "deploy, không gấp): 'Quét đơn xuất kèm' → 'Sửa gộp sai' → 'Cập nhật lý do lệch' — mỗi "
        "nút tự chạy hết toàn bộ danh sách, có tiến độ thấy được ngay, không cần chạm vào server."
    )
