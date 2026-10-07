def migrate(cr, version):
    """Bản trước gộp hóa đơn theo SỐ, mà 2 hóa đơn khác ký hiệu có thể cùng số (hóa đơn thường và
    hóa đơn máy tính tiền). Giờ gộp theo invoice_key (số + ký hiệu + ngày), cần đọc lại chứng từ
    để có ký hiệu:
      - voucher_total = 0 để lần tra tới không đi đường tắt (đường tắt không ghi ký hiệu);
      - xóa lịch tra + cờ đã thu đủ để cả hóa đơn đã thu cũng được đọc lại;
      - bỏ ràng buộc unique theo số hóa đơn cũ của bảng hẹn thu (Odoo không tự bỏ ràng buộc đã
        xóa khỏi code), không thì không lưu được hẹn thu cho 2 hóa đơn cùng số.
    Hẹn thu ghi trước bản này còn nằm trong bảng nhưng chưa có invoice_key nên không hiện — số ít,
    chỉ có trên staging."""
    cr.execute("UPDATE misa_sale_payment_line SET voucher_total = 0")
    cr.execute("""
        UPDATE stock_picking
           SET misa_payment_done = FALSE, misa_payment_checked_at = NULL
         WHERE misa_payment_checked_at IS NOT NULL
    """)
    cr.execute("ALTER TABLE misa_receivable_followup DROP CONSTRAINT IF EXISTS misa_receivable_followup_invoice_no_unique")
