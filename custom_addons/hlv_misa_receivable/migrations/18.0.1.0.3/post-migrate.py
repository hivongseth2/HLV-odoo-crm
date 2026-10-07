# Cùng công thức với misa_receivable_utils.invoice_identity: 'số|ký hiệu|YYYY-MM-DD'.
KEY_SQL = """
    COALESCE(TRIM(invoice_no), '') || '|' || COALESCE(TRIM(invoice_series), '') || '|'
    || COALESCE(TO_CHAR(invoice_date, 'YYYY-MM-DD'), '')
"""


def migrate(cr, version):
    """invoice_key chuyển sang field tính từ số + ký hiệu + ngày đã lưu. Dòng lưu trước bản
    18.0.1.0.2 để rỗng field này nên bị gộp hết vào 1 hàng trên trang — điền lại cho MỌI dòng theo
    đúng công thức mới (dòng chưa có ký hiệu vẫn tách được theo số + ngày, cron đọc lại sẽ bổ sung
    ký hiệu). Hẹn thu đang trỏ khóa cũ thì chuyển sang khóa mới tương ứng trước, để không mất."""
    cr.execute("""
        UPDATE misa_receivable_followup f
           SET invoice_key = k.new_key
          FROM (SELECT DISTINCT ON (invoice_key) invoice_key AS old_key, {key} AS new_key
                  FROM misa_sale_payment_line
                 WHERE invoice_key IS NOT NULL) k
         WHERE f.invoice_key = k.old_key AND k.old_key <> k.new_key
    """.format(key=KEY_SQL))
    cr.execute("UPDATE misa_sale_payment_line SET invoice_key = {key}".format(key=KEY_SQL))
