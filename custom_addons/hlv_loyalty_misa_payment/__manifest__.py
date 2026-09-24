{
    'name': 'HLV Loyalty - Kiểm tra thu tiền hóa đơn MISA',
    'version': '18.0.1.1.0',
    'category': 'Sales',
    'summary': 'Xem hóa đơn MISA của giao dịch điểm đã thu tiền chưa, ngay trên form Lịch sử điểm',
    'description': """
        Khi mở 1 bản ghi Lịch sử điểm, tự tra MISA theo phiếu kho + đơn bán để lấy số hóa đơn,
        rồi đọc chứng từ bán hàng (sa_voucher_get) xem đã thu tiền chưa (paid_type), đối chiếu
        tới TỪNG dòng hàng đã tích điểm (mã hàng + đơn hàng trên chi tiết chứng từ).
        Số hóa đơn + tình trạng thu tiền được lưu lại và hiện ngay trên list Lịch sử điểm;
        cron chạy 20h hằng đêm tra tiếp các bản ghi chưa có hóa đơn hoặc chưa thu tiền.
    """,
    'author': 'HLV',
    # Module cầu nối: form điểm nằm ở hlv_loyalty, còn toàn bộ lớp gọi API MISA
    # (misa.api.utils / misa.config) nằm ở misa_invoice_status_report — đặt riêng ở đây để
    # không module nào trong 2 module đó phải biết tới module kia.
    'depends': ['hlv_loyalty', 'misa_invoice_status_report'],
    'data': [
        'views/loyalty_history_misa_payment_views.xml',
        'data/misa_payment_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_loyalty_misa_payment/static/src/scss/loyalty_misa_payment.scss',
            'hlv_loyalty_misa_payment/static/src/xml/loyalty_misa_payment.xml',
            'hlv_loyalty_misa_payment/static/src/js/loyalty_misa_payment.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
