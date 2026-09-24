"""Đọc ô "hình thức giao hàng" gõ tay thành một mã máy lọc được — hàm thuần.

Sale gõ tay ô ``x_studio_htgh`` nên cùng một ý có hàng chục cách viết: ``GỬI CPN``,
``Gửi chuyển phát nhanh``, ``BOOK GRAB``, ``KHÁCH GHÉ LẤY HÀNG``, ``khách book xe lấy
hàng``… Máy đọc được chuỗi nhưng **không lọc bằng domain được**, nên mỗi lần liệt kê đơn
đều phải kéo hết về rồi tự đọc — chậm và không dùng được trong bộ lọc màn hình.

Không ép sale gõ theo selection: ô đó là của quy trình bán hàng, đổi nó là đổi thói quen
của người khác. Thay vào đó suy ra mã từ chuỗi họ đã gõ.

Không đụng ``self.env``, không ghi gì, không gọi mạng.
"""

from .vtracking_address import strip_accents

# Thứ tự trong danh sách là thứ tự XÉT. Cụ thể xét trước chung chung: "khách book xe lấy
# hàng" chứa cả "book" lẫn "lay hang", "book grab" cũng chứa "book" — nên GRAB và CPN phải
# đứng trước PICKUP, nếu không mọi dòng có chữ "book" đều rơi vào PICKUP.
CHANNEL_RULES = (
    ('grab', ('grab', 'ahamove', 'be delivery', 'giao hang nhanh', 'ghn', 'ghtk')),
    ('express', ('cpn', 'chuyen phat', 'buu dien', 'viettel post', 'vietnam post', 'nha xe')),
    ('pickup', ('ghe lay', 'den lay', 'tu lay', 'khach lay', 'tu den', 'book xe',
                'tu di lay', 'khach tu', 'tu van chuyen', 'tu cho')),
    ('company', ('xe cong ty', 'xe nha', 'cong ty giao', 'xe cua cong ty', 'giao tan noi')),
)

CHANNEL_LABELS = {
    'company': 'Xe công ty',
    'pickup': 'Khách tự lấy',
    'express': 'Chuyển phát nhanh',
    'grab': 'Grab / giao nhanh',
    'other': 'Khác — đọc ghi chú',
}

# Kênh mà xe công ty KHÔNG chạy. Đơn thuộc các kênh này lọt vào kế hoạch là thừa một điểm
# dừng — lỗi đã xảy ra thật khi xếp tay.
CHANNELS_WITHOUT_TRUCK = ('pickup', 'express', 'grab')


def channel_hint(text):
    """Mã kênh nếu chuỗi CÓ dấu hiệu rõ ràng, ngược lại ``None``. Không bao giờ trả 'other'.

    Dùng cho những ô KHÔNG phải ô hình thức giao hàng — ví dụ ô "Nguồn" (``origin``) trên
    đơn, nơi sale hay gõ "CPN", "BOOK GRAB GIAO KHÁCH", "KHÁCH GHÉ LẤY" lẫn với tên khách và
    tên người đặt. Ở những ô như thế, không khớp luật nào nghĩa là **không biết**, chứ không
    phải "sale đã dặn điều gì đó máy chưa hiểu" — nên trả None thay vì ``'other'``.

    :param text: nguyên văn ô, có thể ``None``
    :returns: ``'company' | 'pickup' | 'express' | 'grab' | None``
    """
    clean = strip_accents(text or '').lower()
    for channel, keywords in CHANNEL_RULES:
        if any(keyword in clean for keyword in keywords):
            return channel
    return None


def delivery_channel(text):
    """Chuỗi gõ tay -> một mã trong ``CHANNEL_LABELS``, hoặc ``None`` nếu ô trống.

    Trả về ``'other'`` khi ô CÓ chữ nhưng không khớp luật nào: khác hẳn ô trống, vì nó
    nghĩa là sale đã dặn một điều gì đó mà máy chưa hiểu — người phải đọc, không được lặng
    lẽ coi như giao bằng xe công ty.

    :param text: nguyên văn ô Studio, có thể ``None``
    :returns: ``'company' | 'pickup' | 'express' | 'grab' | 'other' | None``
    """
    if not strip_accents(text or '').strip():
        return None
    return channel_hint(text) or 'other'


def needs_company_truck(channel):
    """Kênh này có cần xe công ty chạy không.

    Ô trống (``None``) coi như CÓ: mặc định của kho là xe nhà giao, và bỏ sót một đơn phải
    giao nguy hiểm hơn hẳn việc xếp thừa một đơn khách tự lấy.
    """
    return channel not in CHANNELS_WITHOUT_TRUCK
