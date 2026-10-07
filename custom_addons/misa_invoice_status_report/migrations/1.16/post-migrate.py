import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Bản trước lấy tiền/ngày HĐ từ chứng từ ĐẦU TIÊN trùng số hóa đơn — 2 HĐ khác ký hiệu có thể
    cùng số (hóa đơn thường và hóa đơn máy tính tiền), phiếu của HĐ cũ hơn nhận nhầm tiền/ngày của
    HĐ kia (xem _pick_voucher_for_invoice). Code mới chỉ sửa cho các lần kiểm từ nay; phiếu cũ đã
    "Đã xuất HĐ" thì cron không kiểm lại.

    CHỈ GHI LOG danh sách phiếu nghi bị nhầm, KHÔNG đổi gì: đưa phiếu về "Chưa kiểm tra" để cron
    tự sửa sẽ tắt lớp chống mất dữ liệu của action_check_misa_invoice_status (chỉ bật khi phiếu
    đang 'invoiced') — lần kiểm theo lô nào không tìm ra đề nghị là xóa số/tiền HĐ đúng đã có.
    Kiểm lại bằng tay theo lệnh in trong log (tra sống từng phiếu, giữ nguyên lớp bảo vệ). Thuần
    DB, không gọi MISA (xem migrations/1.7).

    Nghi bị nhầm = phiếu đã xuất HĐ mang số HĐ mà phiếu khác cũng mang nhưng thuộc ĐỀ NGHỊ khác
    (cùng đề nghị là cùng 1 HĐ gộp, không nhầm được)."""
    cr.execute("""
        SELECT id, name, misa_invoice_no FROM stock_picking
        WHERE misa_invoice_state = 'invoiced'
          AND misa_invoice_no IN (
              SELECT misa_invoice_no FROM stock_picking
              WHERE misa_invoice_state = 'invoiced' AND misa_invoice_no IS NOT NULL
                AND misa_invoice_request_refid IS NOT NULL
              GROUP BY misa_invoice_no
              HAVING COUNT(DISTINCT misa_invoice_request_refid) > 1
          )
        ORDER BY misa_invoice_no, name
    """)
    rows = cr.fetchall()
    if not rows:
        _logger.info("✅ [MISA 1.16] Không có phiếu nào mang số HĐ trùng giữa các đề nghị.")
        return
    _logger.warning(
        "⚠️ [MISA 1.16] %s phiếu mang số HĐ trùng giữa các đề nghị (có thể đang ghi nhầm tiền/ngày "
        "của HĐ khác ký hiệu): %s\nKiểm lại trong odoo-bin shell:\n"
        "    env['stock.picking'].browse(%s).action_check_misa_invoice_status(); env.cr.commit()",
        len(rows), ', '.join('%s (HĐ %s)' % (name, invoice_no) for _id, name, invoice_no in rows),
        [row[0] for row in rows],
    )
