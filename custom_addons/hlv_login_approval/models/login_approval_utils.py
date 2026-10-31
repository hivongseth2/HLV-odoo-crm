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


def request_expiry(requested_at, valid_minutes):
    """Tính thời điểm yêu cầu duyệt hết hạn.

    :param datetime requested_at: thời điểm gửi yêu cầu.
    :param int valid_minutes: số phút yêu cầu còn chờ được.
    :return: datetime = requested_at + valid_minutes phút.
    """
    return requested_at + timedelta(minutes=valid_minutes)


def is_request_open(state, request_until, now):
    """Yêu cầu duyệt còn chờ được (chưa ai xử lý và chưa quá hạn) không.

    :param str state: trạng thái bản ghi thiết bị.
    :param request_until: datetime hết hạn yêu cầu, hoặc False/None.
    :param datetime now: thời điểm đang xét.
    :return: True chỉ khi state là 'pending' và chưa quá request_until.
        Thiếu request_until (yêu cầu tạo trước khi có hạn) thì coi như đã hết hạn.
    """
    return state == 'pending' and bool(request_until) and now < request_until


def join_match_choices(numbers):
    """Ghép bộ số cho người duyệt chọn thành chuỗi để lưu.

    :param numbers: các số nguyên (số đúng lẫn số mồi), thứ tự bất kỳ.
    :return: chuỗi các số xếp tăng dần, ngăn cách bằng dấu phẩy, ví dụ "12,47,83".
        Xếp tăng dần để vị trí nút không lộ số nào là số đúng. Rỗng thì trả "".
    """
    return ','.join(str(n) for n in sorted(numbers))


def split_match_choices(value):
    """Tách chuỗi bộ số đã lưu thành danh sách để hiện lên nút.

    :param value: chuỗi dạng "12,47,83", hoặc False/None.
    :return: list chuỗi số theo thứ tự đã lưu; value rỗng thì trả [].
    """
    return [part for part in (value or '').split(',') if part]
