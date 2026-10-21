"""Khoảng thời gian cho bộ lọc "Thời gian" của ô tìm tin nhắn.

Dùng chung cho drawer tin nhắn trang điều phối (OWL) và panel tìm tin nhắn trang
/sale_plan: cả hai chỉ gửi lựa chọn (period + ngày tự chọn), còn quy đổi ra khoảng
ngày nằm một chỗ ở đây để hai màn hình không hiểu "7 ngày qua" khác nhau.
"""

from datetime import datetime, timedelta

import pytz

# Số ngày lùi lại tính từ hôm nay (hôm nay tính là 1 ngày).
_ROLLING_DAYS = {'today': 0, '7d': 6, '30d': 29}


def _parse_day(value):
    try:
        return datetime.strptime((value or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def message_period_bounds(period, today, date_from='', date_to=''):
    """Đổi lựa chọn thời gian thành khoảng ngày địa phương.

    Nhận:
        period: '' | 'today' | 'yesterday' | '7d' | '30d' | 'custom'.
        today: date hôm nay theo giờ địa phương.
        date_from, date_to: 'YYYY-MM-DD', chỉ dùng khi period = 'custom'.
    Trả: (from_day, to_day) kiểu date, cả hai đầu đều tính vào; đầu nào không giới
    hạn là None.
    Biên: period rỗng / không biết → (None, None). Ngày tự chọn sai định dạng → bỏ
    đầu đó. from_day > to_day (gõ ngược) → đảo lại thay vì trả tập rỗng.
    """
    if period in _ROLLING_DAYS:
        return today - timedelta(days=_ROLLING_DAYS[period]), today
    if period == 'yesterday':
        day = today - timedelta(days=1)
        return day, day
    if period == 'custom':
        from_day, to_day = _parse_day(date_from), _parse_day(date_to)
        if from_day and to_day and from_day > to_day:
            from_day, to_day = to_day, from_day
        return from_day, to_day
    return None, None


def local_days_to_utc_range(from_day, to_day, tz):
    """Đổi khoảng ngày địa phương sang mốc UTC (naive) để so với mail.message.date.

    Nhận: from_day, to_day (date hoặc None), tz (pytz timezone).
    Trả: (start_utc, end_utc) — lọc dạng start_utc <= date < end_utc; end_utc là
    0h ngày SAU to_day. Đầu nào None thì trả None ở đầu đó.
    """
    def to_utc(day):
        local = tz.localize(datetime.combine(day, datetime.min.time()))
        return local.astimezone(pytz.UTC).replace(tzinfo=None)

    start_utc = to_utc(from_day) if from_day else None
    end_utc = to_utc(to_day + timedelta(days=1)) if to_day else None
    return start_utc, end_utc
