import hashlib
from datetime import timedelta


def hash_device_token(token):
    """Băm token cookie thiết bị để lưu DB.

    :param str token: giá trị cookie thiết bị (chuỗi ngẫu nhiên).
    :return: chuỗi hex SHA-256 dài 64 ký tự. Token rỗng vẫn trả về hash của chuỗi rỗng,
        việc chặn token rỗng là của người gọi.
    """
    return hashlib.sha256((token or '').encode()).hexdigest()


def parse_positive_int(value, default):
    """Đọc số nguyên dương từ tham số cấu hình (dạng chuỗi).

    :param value: giá trị đọc từ ir.config_parameter (str hoặc None).
    :param int default: giá trị trả khi value rỗng, không phải số, hoặc <= 0.
    :return: int > 0.
    """
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def approval_expiry(approved_at, valid_days):
    """Tính thời điểm hết hạn duyệt.

    :param datetime approved_at: thời điểm duyệt.
    :param int valid_days: số ngày hiệu lực.
    :return: datetime = approved_at + valid_days ngày.
    """
    return approved_at + timedelta(days=valid_days)


def is_approval_valid(state, approved_until, now):
    """Thiết bị có đang được phép đăng nhập không.

    :param str state: trạng thái bản ghi thiết bị ('pending' / 'approved' / 'rejected').
    :param approved_until: datetime hết hạn, hoặc False/None nếu chưa duyệt.
    :param datetime now: thời điểm đang xét.
    :return: True chỉ khi state là 'approved' và chưa quá approved_until.
        Đã duyệt mà thiếu approved_until thì coi như không hợp lệ.
    """
    return state == 'approved' and bool(approved_until) and now < approved_until
