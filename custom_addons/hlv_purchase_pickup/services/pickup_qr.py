"""Dựng URL và ảnh QR cho chuyến đi nhận — hàm thuần, không gọi mạng, không đụng env.

Mã QR trên tờ lịch in ra trỏ thẳng vào màn hình đi nhận của ĐÚNG chuyến đó. Người đi nhận
quét một cái là mở app, không phải tự tìm chuyến của mình trong danh sách.

QR chỉ chứa một URL công khai, KHÔNG chứa token hay dữ liệu gì: `/pickup` vẫn đòi đăng nhập
như thường, và server vẫn kiểm chuyến đó có phải của người quét không. Ai nhặt được tờ giấy
cũng không xem được gì thêm so với khi họ tự gõ địa chỉ.
"""

from urllib.parse import quote


def pickup_page_url(base_url, run_id):
    """Địa chỉ mở thẳng một chuyến trên trang /pickup.

    base_url: giá trị tham số hệ thống ``web.base.url``, có hay không có dấu / cuối đều được.
    Trả về chuỗi URL tuyệt đối. base_url rỗng thì trả đường dẫn tương đối — quét sẽ không ra
    gì, nên nơi gọi phải bảo đảm đã khai web.base.url.
    """
    base = (base_url or '').strip().rstrip('/')
    return '%s/pickup?run=%s' % (base, int(run_id))


def qr_image_src(target_url, size=180):
    """Đường dẫn ảnh QR do chính Odoo sinh (route /report/barcode của module web).

    Dùng route sẵn có thay vì tự sinh ảnh: không thêm phụ thuộc thư viện, và wkhtmltopdf đọc
    được đường dẫn nội bộ này khi kết xuất PDF.

    target_url: nội dung nhúng vào mã QR. size: cạnh ảnh tính bằng pixel.
    Trả về chuỗi dùng thẳng cho thuộc tính src.
    """
    return '/report/barcode/?barcode_type=QR&value=%s&width=%s&height=%s' % (
        quote(target_url or '', safe=''), int(size), int(size),
    )
