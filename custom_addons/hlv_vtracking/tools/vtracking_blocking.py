"""Cờ chặn của một đơn hàng — hàm thuần, vào gì ra nấy.

Vì sao cần chuẩn hoá: người điều phối biết "Coherent phải khai hải quan" và "Imarket gửi
CPN", nhưng biết trong đầu. AI đọc API thì chỉ thấy vài chuỗi rời rạc, phải tự suy — và
suy sai một lần là xe tới cổng khu chế xuất rồi phải chở hàng về.

Hai mức, đừng trộn:

* **cứng** (``hard=True``) — xếp lên xe là hỏng chuyến. Thủ tục chưa xong thì bảo vệ không
  cho vào cổng. `hlv.vtracking.plan.action_confirm` CHẶN ở mức này.
* **mềm** — xếp được nhưng gần như chắc chắn là thừa: khách tự lấy, gửi CPN, book Grab.
  Không chặn vì "lần này khác thường lệ" là chuyện có thật.

Không đụng ``self.env``, không ghi gì, không gọi mạng.
"""

from .vtracking_channel import CHANNEL_LABELS, CHANNELS_WITHOUT_TRUCK

PROCEDURE_LABELS = {
    'none': 'Không cần',
    'customs': 'Khai hải quan',
    'register': 'Đăng ký trước',
    'both': 'Hải quan + đăng ký',
}

# Một thủ tục -> các mã cờ nó sinh ra. 'both' sinh hai cờ chứ không sinh một cờ tên "both":
# bên đọc chỉ cần hỏi "có 'customs' không", không phải liệt kê mọi tổ hợp.
PROCEDURE_FLAGS = {
    'customs': ('customs',),
    'register': ('register',),
    'both': ('customs', 'register'),
}

FLAG_LABELS = {
    'customs': 'Phải khai hải quan trước khi xe vào',
    'register': 'Phải đăng ký người và xe trước',
}


def blocking_flags(procedure_required=None, delivery_channel=None):
    """Các cờ chặn của một điểm giao, đã chuẩn hoá.

    :param procedure_required: ``none`` | ``customs`` | ``register`` | ``both`` | None
    :param delivery_channel: mã kênh giao (xem ``vtracking_channel``), có thể None
    :returns: list dict ``{'code', 'label', 'hard'}``, rỗng nếu không vướng gì.

    Thứ tự: cờ CỨNG trước, để bên nào chỉ đọc phần tử đầu vẫn thấy thứ nguy hiểm nhất.
    """
    flags = [
        {'code': code, 'label': FLAG_LABELS[code], 'hard': True}
        for code in PROCEDURE_FLAGS.get(procedure_required or 'none', ())
    ]
    if delivery_channel in CHANNELS_WITHOUT_TRUCK:
        flags.append({
            'code': delivery_channel,
            'label': '%s — xe công ty không phải chạy' % CHANNEL_LABELS[delivery_channel],
            'hard': False,
        })
    return flags


def has_hard_block(flags):
    """Trong danh sách cờ có cái nào chặn cứng không."""
    return any(flag['hard'] for flag in flags)
