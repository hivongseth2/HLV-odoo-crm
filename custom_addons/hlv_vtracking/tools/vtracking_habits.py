"""Thói quen khách đã đo được khi chạy tay — bảng mồi và hàm khớp tên. Hàm thuần.

Nguồn: hội thoại điều phối kho Bến Cam, 15 khách đầu tiên đã rút ra được quy luật. Đây là
tri thức ĐẮT: mỗi dòng ứng với một lần xếp sai ngoài thực tế rồi mới biết. Để nó nằm trong
đầu người điều phối thì ngày họ nghỉ là ngày kế hoạch sai lại từ đầu.

Chỉ mồi, không khoá: người dùng sửa được mọi dòng sau khi tạo, và mồi lần hai không đè lên
cái họ đã sửa.

Không đụng ``self.env``, không ghi gì, không gọi mạng.
"""

from .vtracking_address import strip_accents

# Mỗi dòng: (từ khoá nhận tên điểm, giá trị thói quen).
# Từ khoá khớp theo TỪ NGUYÊN, không khớp chuỗi con: "hory" nằm lọt trong nhiều tên khác,
# khớp chuỗi con thì một điểm không liên quan cũng bị gán "phải khai hải quan".
KNOWN_HABITS = (
    # --- Khu chế xuất: phải khai hải quan trước khi xe vào ------------------
    ('coherent', {'procedure_required': 'customs'}),
    ('jabil', {'procedure_required': 'customs'}),
    ('pegasus shimamoto', {'procedure_required': 'customs'}),
    ('hory', {'procedure_required': 'customs'}),
    ('om digital', {'procedure_required': 'customs'}),

    # --- Phải đăng ký người/xe trước ----------------------------------------
    # Hyosung có ba pháp nhân; từ khoá một chữ để bắt cả ba.
    ('hyosung', {'procedure_required': 'register'}),
    ('serveone', {'procedure_required': 'register'}),
    ('ton nam kim phu my', {'procedure_required': 'register'}),

    # --- Khách tự ghé lấy: KHÔNG xếp lên xe ---------------------------------
    ('anh thang phat', {'delivery_method': 'pickup'}),
    ('thien hoa', {'delivery_method': 'pickup'}),
    ('lucky sk', {'delivery_method': 'pickup'}),
    ('thien loc thien', {'delivery_method': 'pickup'}),

    # --- Gửi ngoài: CPN hoặc book Grab --------------------------------------
    # Nguồn gộp chung "CPN / book Grab" nên chưa tách được ai dùng kênh nào. Đặt 'express'
    # cho cả ba: hai kênh khác nhau ở chỗ ai đi giao, nhưng GIỐNG nhau ở điều duy nhất kế
    # hoạch quan tâm — không chiếm một điểm dừng của xe công ty.
    ('imarket', {'delivery_method': 'express',
                 'free_note': 'Nguồn ghi "CPN / book Grab" — xác nhận lại kênh cụ thể.'}),
    ('hiep phuoc thanh', {'delivery_method': 'express',
                          'free_note': 'Nguồn ghi "CPN / book Grab" — xác nhận lại kênh cụ thể.'}),
    ('stolz', {'delivery_method': 'express',
               'free_note': 'Nguồn ghi "CPN / book Grab" — xác nhận lại kênh cụ thể.'}),
)


def _words(value):
    """Tên -> danh sách từ thường, không dấu. Dấu câu coi như khoảng trắng."""
    clean = strip_accents(value or '').lower()
    return [word for word in ''.join(
        char if char.isalnum() else ' ' for char in clean
    ).split() if word]


def match_known_habits(place_name):
    """Tên điểm giao -> dict thói quen đã biết, hoặc ``None`` nếu không khớp dòng nào.

    Khớp khi TẤT CẢ các từ của từ khoá xuất hiện liền nhau trong tên điểm. Liền nhau chứ
    không rời rạc: "Thiên Hoà" phải là hai từ cạnh nhau, không phải "Thiên Phú ... Hoà An".

    Dòng đầu khớp được dùng; bảng xếp theo nhóm nên từ khoá không chồng nhau.

    :param place_name: tên điểm giao, có dấu cũng được
    :returns: dict các cột thói quen (đã kèm ``free_note`` nếu có), hoặc ``None``
    """
    words = _words(place_name)
    if not words:
        return None
    for keyword, habits in KNOWN_HABITS:
        needle = _words(keyword)
        span = len(needle)
        if any(words[i:i + span] == needle for i in range(len(words) - span + 1)):
            return dict(habits)
    return None
