def migrate(cr, version):
    """Bản 1.0.0 chỉ gắn dòng chứng từ MISA theo mã đơn ghi trên chứng từ — mà kế toán thường bỏ
    trống cột đó, nên nhiều dòng không gắn được. Hóa đơn đã thu đủ lại không bao giờ được tra lại
    (misa_payment_done), nên phải xóa lịch tra để cron tra lại hết với cách khớp mới."""
    cr.execute("""
        UPDATE stock_picking
           SET misa_payment_done = FALSE, misa_payment_checked_at = NULL
         WHERE misa_payment_checked_at IS NOT NULL
    """)
