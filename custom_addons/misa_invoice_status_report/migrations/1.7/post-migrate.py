import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Giới hạn số lô xử lý trong migration (mỗi lô có thể gọi thêm 1 API MISA/phiếu) — tránh
# migration chạy quá lâu/timeout nếu dữ liệu quá nhiều; phần còn sót (nếu có) xử lý tiếp bằng
# các nút quét/sửa tương ứng trên dashboard (đều tự động chạy hết toàn bộ danh sách khi bấm).
MAX_BATCHES = 10
BATCH_SIZE = 100


def migrate(cr, version):
    """Bản 1.6 đã lên production TRƯỚC KHI có loạt fix sau cùng của module này (loại trừ phiếu
    đã tự có hóa đơn độc lập khỏi diện "còn trống có thể nhận" trong
    _misa_invoice_discover_grouped_orders, Cơ chế A không còn gán "ăn theo" mù mà giao hẳn cho
    engine khớp dòng hàng quyết định, sửa gán lồng nhau, đối chiếu dòng hàng cho CHÍNH phiếu
    trong nhóm chứ không chỉ các đơn khác...). Vì version manifest không đổi lúc đó
    (migrations/1.6 đã chạy 1 lần với code CŨ hơn), các fix sau cùng sẽ KHÔNG được áp dụng lại
    cho dữ liệu cũ nếu không có migration mới — bump lên 1.7 và chạy lại đầy đủ 4 bước bảo trì
    (tương đương 4 nút trên dashboard: Quét đơn xuất kèm / Sửa gộp sai / Sửa gán lồng nhau / Cập
    nhật lý do lệch) bằng CODE MỚI NHẤT, để không phải nhớ bấm tay sau khi deploy."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Picking = env['stock.picking'].sudo()

    # 1) Quét lại TOÀN BỘ phiếu đại diện đã từng được quét (group_checked=True) bằng logic mới
    # (loại trừ phiếu đã tự có hóa đơn độc lập khỏi diện "còn trống có thể nhận").
    to_rescan = Picking.search([
        ('picking_type_id.code', '=', 'outgoing'),
        ('misa_invoice_state', '=', 'invoiced'),
        ('misa_invoice_master_picking_id', '=', False),
        ('misa_invoice_request_refid', '!=', False),
        ('misa_invoice_group_checked', '=', True),
    ])
    to_rescan.write({'misa_invoice_group_checked': False})
    _logger.info(
        "🔄 [MISA 1.7] Bước 1/4 — reset misa_invoice_group_checked cho %s phiếu đại diện để quét lại "
        "bằng logic mới nhất.", len(to_rescan),
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
        "✅ [MISA 1.7] Bước 1/4 hoàn tất: đã quét lại %s phiếu, phát hiện thêm %s phiếu xuất kèm.",
        total_checked, total_discovered,
    )

    # 2) Sửa các phiếu bị gán "ăn theo" SAI (đề nghị chỉ phủ 1 phần giá trị của phiếu đó).
    total_checked = 0
    total_reverted = 0
    for _i in range(MAX_BATCHES):
        result = Picking.repair_misa_invoice_grouped_orders(limit=BATCH_SIZE)
        total_checked += result['checked']
        total_reverted += result['reverted']
        if result['checked'] < BATCH_SIZE:
            break
    _logger.info(
        "✅ [MISA 1.7] Bước 2/4 hoàn tất: đã kiểm tra %s phiếu đại diện, sửa lại %s phiếu bị gán sai.",
        total_checked, total_reverted,
    )

    # 3) Sửa các phiếu bị gán "ăn theo" LỒNG NHAU (chain 2+ tầng).
    total_checked = 0
    total_flattened = 0
    for _i in range(MAX_BATCHES):
        result = Picking.flatten_misa_invoice_master_chains(limit=BATCH_SIZE * 2)
        total_checked += result['checked']
        total_flattened += result['flattened']
        if result['checked'] < BATCH_SIZE * 2:
            break
    _logger.info(
        "✅ [MISA 1.7] Bước 3/4 hoàn tất: đã kiểm tra %s phiếu, sửa %s phiếu bị gán lồng nhau.",
        total_checked, total_flattened,
    )

    # 4) Gộp hóa đơn trùng (request_refid trùng nhau ở nhiều phiếu 'invoiced' chưa liên kết) —
    # lưới an toàn dự phòng, nay đã flatten cả nhóm thay vì chỉ phần "ungrouped" (xem
    # _misa_invoice_dedupe_request_refid_groups).
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
        _logger.info("✅ [MISA 1.7] Bước 4/4 (dedupe) hoàn tất: đã kiểm tra %s mã request_refid trùng.", len(refids))
    except Exception:
        _logger.exception("❌ [MISA 1.7] Lỗi ở bước dedupe.")

    # 5) Cập nhật lý do lệch (misa_invoice_gap_summary) cho các nhóm đang lệch — để danh sách
    # "Đối chiếu tổng" hiện đúng lý do mới (not_matched/conflict/self_unconfirmed) ngay khi vừa
    # deploy, không cần bấm tay "Cập nhật lý do lệch".
    total_checked = 0
    for _i in range(MAX_BATCHES):
        result = Picking.refresh_misa_invoice_gap_summaries(limit=BATCH_SIZE)
        total_checked += result['checked']
        if result['checked'] < BATCH_SIZE:
            break
    _logger.info("✅ [MISA 1.7] Bước 5/5 hoàn tất: đã cập nhật lý do lệch cho %s phiếu.", total_checked)

    _logger.info(
        "✅ [MISA 1.7] Backfill toàn bộ hoàn tất (nếu còn sót do vượt quá %s lô ở bước nào, dùng "
        "đúng nút tương ứng trên dashboard để chạy tiếp — mỗi nút giờ tự chạy hết toàn bộ danh "
        "sách trong 1 lần bấm).", MAX_BATCHES,
    )
