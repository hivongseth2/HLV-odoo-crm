import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Fix dữ liệu cũ bị tính TRÙNG tiền hóa đơn: cơ chế gộp hóa đơn (master_refno) dựa vào
    MISA tự báo đúng TÊN phiếu đại diện — nếu MISA lưu refno không khớp tên phiếu Odoo nào (VD
    kế toán tự đặt mã khi tạo hóa đơn gộp nhiều phiếu), việc tìm phiếu gốc thất bại và MỖI phiếu
    cùng khớp vào hóa đơn đó tự ghi ĐỦ 100% tiền hóa đơn cho riêng mình — tính trùng N lần cho
    đúng 1 hóa đơn (N = số phiếu bị match nhầm). Ví dụ thật: 8 phiếu KBC/OUT/... của cùng 1
    khách đều ghi misa_invoice_amount = 87.794.388đ (cùng misa_invoice_no, cùng
    misa_invoice_request_refid) dù đó chỉ là 1 hóa đơn duy nhất — thổi phồng "Tổng đã xuất HĐ"
    thêm ~614 triệu chỉ riêng ca này.

    Quét toàn bộ misa_invoice_request_refid đang bị trùng ở nhiều phiếu 'invoiced' và gộp lại
    qua _misa_invoice_dedupe_request_refid_groups() — xem chi tiết thuật toán chọn đại diện ở
    đó. Từ nay việc kiểm tra MISA (action_check_misa_invoice_status) cũng tự chạy bước này sau
    mỗi lần kiểm tra, nên chỉ cần backfill 1 lần cho dữ liệu cũ."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Picking = env['stock.picking'].sudo()

    env.cr.execute("""
        SELECT misa_invoice_request_refid
        FROM stock_picking
        WHERE misa_invoice_state = 'invoiced' AND misa_invoice_request_refid IS NOT NULL
        GROUP BY misa_invoice_request_refid
        HAVING COUNT(*) > 1
    """)
    refids = [row[0] for row in env.cr.fetchall()]

    _logger.info("🔄 [MISA DEDUPE] Tìm thấy %s mã request_refid bị trùng ở nhiều phiếu.", len(refids))
    try:
        Picking._misa_invoice_dedupe_request_refid_groups(request_refids=refids)
        _logger.info("✅ [MISA DEDUPE] Gộp hóa đơn trùng hoàn tất.")
    except Exception:
        _logger.exception("❌ [MISA DEDUPE] Lỗi khi gộp hóa đơn trùng.")
