{
    'name': 'MISA - Thu tiền theo dòng đơn bán & công nợ phải thu',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Tình trạng thu tiền MISA lưu trên từng dòng đơn bán + tab "Công nợ phải thu" trên /misa_sale_status',
    'description': """
        Với mỗi hóa đơn đã ghi nhận trên phiếu xuất kho (misa_invoice_no), đọc chứng từ bán hàng
        MISA (đã thu / chưa thu) và chi tiết từng dòng hàng, gắn về đúng dòng đơn bán Odoo theo
        mã đơn + mã hàng (kể cả mã con của combo). Kết quả lưu trên dòng đơn bán: tiền đã lên
        chứng từ, đã thu, chưa thu, số hóa đơn, tình trạng thu.

        Trang /misa_sale_status có thêm tab "Công nợ phải thu": các hóa đơn còn phần chưa thu,
        hạn thu theo điều khoản thanh toán của đơn, nhóm quá hạn, chi tiết theo dòng đơn bán, sale
        ghi ngày hẹn thu / xác suất thu / ghi chú.
    """,
    'author': 'HLV',
    # misa_invoice_status_report: số hóa đơn trên phiếu, trang /misa_sale_status, xác thực mã sale
    # và lớp gọi API MISA (misa.api.utils) đều nằm ở đó. sale_stock: move_ids trên dòng đơn bán
    # (để biết mã sản phẩm con của combo).
    'depends': ['misa_invoice_status_report', 'sale_stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/misa_receivable_cron.xml',
        'views/misa_sale_status_receivable_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
