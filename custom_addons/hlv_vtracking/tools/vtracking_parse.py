"""Bóc dữ liệu vTracking Open API — hàm thuần, vào gì ra nấy.

Không đụng ``self.env``, không gọi mạng, không side effect. Mọi chỗ trong module đổi
thời gian hoặc so biển số đều phải đi qua đây: vTracking trả epoch mili-giây còn Odoo
lưu Datetime naive UTC, sai một chỗ là lệch 7 tiếng và bản ghi rơi sang ngày khác mà
không ai nhận ra ngay.
"""

import re
from datetime import datetime, time, timedelta, timezone

# Trạng thái phương tiện theo tài liệu 1.0.3. Giữ nguyên chuỗi gốc của vTracking, không
# dịch sang mã riêng: đổi tên ở đây thì mọi so sánh với payload sau này đều phải nhớ dịch.
VEHICLE_STATUSES = ('run', 'stop', 'park', 'offline', 'badgps')

# Toạ độ lấy từ ping có trạng thái này không đáng tin — thiết bị mất sóng vẫn gửi toạ độ
# cũ hoặc toạ độ rác.
UNTRUSTED_STATUSES = ('offline', 'badgps')

# 12 cờ cảnh báo trong attribute_key = "alarm". Chỉ giữ cờ có ý nghĩa vận hành với nhãn
# tiếng Việt; cờ lỗi phần cứng để nguyên tên vì kỹ thuật vTracking đọc theo tên đó.
ALARM_LABELS = {
    'sos': 'SOS',
    'collisionVehicle': 'Va chạm',
    'abnormalFuel': 'Nhiên liệu bị rút',
    'timeOutContinuousDrivingTime': 'Lái quá 4h liên tục',
    'timeOutDrivingTime': 'Lái quá 10h/ngày',
    'timeoutParking': 'Đỗ quá thời gian',
    'turnOffMainPowerVol': 'Nguồn bị rút',
    'underMainPowerVol': 'Ắc quy yếu',
    'overMainPowerVol': 'Ắc quy quá áp',
    'malfunctionModuleGnss': 'Lỗi module GPS',
    'malfunctionAntenGnss': 'Lỗi anten GPS',
    'shortCircuitedGnss': 'GPS ngắn mạch',
}

_NON_ALNUM_RE = re.compile(r'[^0-9A-Za-z]+')


def normalize_plate(value):
    """Biển số rút về dạng so khớp được: chỉ chữ và số, viết hoa.

    vTracking ghi ``51C77577`` còn Odoo có thể ghi ``51C-775.77``, ``51c 77577``.
    Ghép theo chuỗi thô sẽ trượt gần hết đội xe.

    Trả về chuỗi rỗng khi đầu vào rỗng/None.
    """
    if not value:
        return ''
    return _NON_ALNUM_RE.sub('', str(value)).upper()


def ms_to_utc_naive(value):
    """Epoch mili-giây -> ``datetime`` naive UTC (đúng dạng Odoo lưu vào Datetime).

    Trả về None nếu không đọc được số, hoặc số <= 0. Nhận cả int lẫn chuỗi số vì
    vTracking trả ``ts`` dạng int nhưng ``last_update_ts`` có bản ghi trả chuỗi.
    """
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc).replace(tzinfo=None)


def utc_naive_to_ms(value):
    """``datetime`` naive UTC -> epoch mili-giây. None vào thì None ra."""
    if not value:
        return None
    return int(value.replace(tzinfo=timezone.utc).timestamp() * 1000)


def day_bounds_ms(day, tz):
    """Mốc đầu và cuối của MỘT NGÀY ĐỊA PHƯƠNG, tính ra epoch mili-giây.

    day: ``date``. tz: đối tượng tzinfo (thường là ``pytz.timezone('Asia/Ho_Chi_Minh')``).
    Trả về tuple ``(start_ms, end_ms)``, end là 23:59:59.999 cùng ngày.

    Luôn phải truyền mốc tường minh khi gọi API: mặc định của vTracking là "đầu ngày hôm
    trước" tính theo giờ server của họ, không phải giờ của mình.
    """
    start_local = _localize(datetime.combine(day, time.min), tz)
    end_local = _localize(datetime.combine(day, time.min) + timedelta(days=1), tz)
    start_ms = int(start_local.timestamp() * 1000)
    end_ms = int(end_local.timestamp() * 1000) - 1
    return start_ms, end_ms


def attributes_by_key(attributes):
    """Mảng ``attributes`` của API -> dict ``{attribute_key: {value, last_update_ts}}``.

    Phần tử thiếu ``attribute_key`` bị bỏ qua thay vì ném lỗi: API có thể thêm thuộc
    tính mới bất cứ lúc nào và không đáng để làm gãy cả lượt đồng bộ.
    """
    result = {}
    for item in attributes or []:
        if not isinstance(item, dict):
            continue
        key = item.get('attribute_key')
        if not key:
            continue
        result[key] = {
            'value': item.get('value'),
            'last_update_ts': item.get('last_update_ts'),
        }
    return result


def parse_vehicle(raw):
    """Một phần tử ``vehicles[]`` -> dict phẳng dùng được ngay để ghi vào Odoo.

    Trả về None nếu thiếu ``id`` hoặc thiếu biển số — không có hai thứ đó thì không ghép
    được với xe nào trong Odoo, giữ lại cũng vô dụng.

    Khoá trả về: vtracking_id, license_plate, plate_key, vehicle_name, org_name,
    latitude, longitude, speed, direction, status, geocoding, odometer, position_at,
    status_since, acc, door, driver_name, driver_license, alarms (list mã cờ đang bật).
    Trường không có trong payload trả về None, không trả 0 — 0 là một giá trị hợp lệ
    của tốc độ và công-tơ-mét.
    """
    if not isinstance(raw, dict):
        return None
    vtracking_id = (raw.get('id') or '').strip()
    plate = (raw.get('license_plate') or '').strip()
    if not vtracking_id or not plate:
        return None

    attrs = attributes_by_key(raw.get('attributes'))
    datas = attrs.get('datas', {}).get('value') or {}
    if not isinstance(datas, dict):
        datas = {}

    result = {
        'vtracking_id': vtracking_id,
        'license_plate': plate,
        'plate_key': normalize_plate(plate),
        'vehicle_name': (raw.get('vehicle_name') or '').strip(),
        'org_name': (raw.get('org_name') or '').strip(),
        'latitude': _as_float(datas.get('latitude')),
        'longitude': _as_float(datas.get('longitude')),
        'speed': _as_float(datas.get('speed')),
        'direction': _as_float(datas.get('direction')),
        'odometer': _as_float(datas.get('odometer')),
        'status': _as_status(datas.get('status')),
        'geocoding': (datas.get('geocoding') or '').strip() or None,
        # Ưu tiên timestamp trong "datas": đó là lúc THIẾT BỊ gửi tin. last_update_ts là
        # lúc máy chủ vTracking ghi nhận, muộn hơn và có thể nhảy khi họ xử lý lại hàng đợi.
        'position_at': (
            ms_to_utc_naive(datas.get('timestamp'))
            or ms_to_utc_naive(attrs.get('datas', {}).get('last_update_ts'))
        ),
        # Với attribute_key = "status", last_update_ts là thời điểm BẮT ĐẦU trạng thái
        # (tài liệu §1.1), nhờ đó biết xe đã đứng yên bao lâu mà không cần gọi hành trình.
        'status_since': ms_to_utc_naive(attrs.get('status', {}).get('last_update_ts')),
        'acc': _as_sensor(attrs.get('acc', {}).get('value')),
        'door': _as_sensor(attrs.get('door', {}).get('value')),
        'driver_name': _as_text(attrs.get('driverName', {}).get('value')),
        'driver_license': _as_text(attrs.get('driverLicense', {}).get('value')),
        'alarms': parse_alarms(attrs.get('alarm', {}).get('value')),
    }
    # "status" ở cấp thuộc tính đáng tin hơn khi "datas" không kèm trạng thái.
    if not result['status']:
        result['status'] = _as_status(attrs.get('status', {}).get('value'))
    return result


def parse_alarms(value):
    """Giá trị của ``attribute_key = "alarm"`` -> list mã cờ ĐANG BẬT.

    API trả 0/1 cho từng cờ. Chỉ giữ cờ khác 0 và có trong ``ALARM_LABELS``: cờ lạ
    xuất hiện sau này sẽ bị bỏ qua thay vì hiện ra một mã trần không ai hiểu.
    Không phải dict thì trả list rỗng.
    """
    if not isinstance(value, dict):
        return []
    return [key for key in ALARM_LABELS if _as_float(value.get(key))]


def alarm_labels(codes):
    """List mã cờ -> chuỗi nhãn tiếng Việt, ngăn bằng dấu phẩy. Rỗng thì trả ''."""
    return ', '.join(ALARM_LABELS[code] for code in codes or [] if code in ALARM_LABELS)


def parse_journey_logs(payload):
    """Payload của endpoint hành trình -> list dict ping đã sắp theo thời gian tăng dần.

    Mỗi ping: ``{ts (datetime naive UTC), latitude, longitude, speed, direction,
    status, geocoding}``. Ping thiếu thời gian hoặc thiếu toạ độ bị loại — vẽ lên bản
    đồ không được mà tính quãng đường cũng không được.

    Payload không phải dict thì trả list rỗng.
    """
    if not isinstance(payload, dict):
        return []
    result = []
    for item in payload.get('logs') or []:
        if not isinstance(item, dict):
            continue
        moment = ms_to_utc_naive(item.get('ts'))
        value = item.get('value')
        if not moment or not isinstance(value, dict):
            continue
        latitude = _as_float(value.get('latitude'))
        longitude = _as_float(value.get('longitude'))
        if latitude is None or longitude is None:
            continue
        result.append({
            'ts': moment,
            'latitude': latitude,
            'longitude': longitude,
            'speed': _as_float(value.get('speed')),
            'direction': _as_float(value.get('direction')),
            'status': _as_status(value.get('status')),
            'geocoding': (value.get('geocoding') or '').strip() or None,
        })
    result.sort(key=lambda ping: ping['ts'])
    return result


def journey_distance_km(payload):
    """``additional_info.d`` — quãng đường (km) của đúng các bản ghi trong payload.

    Trả về 0.0 khi không có. Cộng dồn qua từng trang mới ra quãng đường cả khoảng thời
    gian, vì mỗi lần gọi chỉ tính trên phần bản ghi nó trả về.
    """
    if not isinstance(payload, dict):
        return 0.0
    info = payload.get('additional_info')
    if not isinstance(info, dict):
        return 0.0
    return _as_float(info.get('d')) or 0.0


def _localize(naive_dt, tz):
    """Gắn tzinfo cho datetime naive, chạy được với cả pytz lẫn zoneinfo."""
    if hasattr(tz, 'localize'):
        return tz.localize(naive_dt)
    return naive_dt.replace(tzinfo=tz)


def _as_float(value):
    """float hoặc None. Chuỗi rỗng, None, giá trị không đọc được đều ra None."""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_status(value):
    """Trạng thái hợp lệ theo tài liệu, hoặc None."""
    text = (value or '') if isinstance(value, str) else ''
    text = text.strip().lower()
    return text if text in VEHICLE_STATUSES else None


def _as_sensor(value):
    """Cảm biến active/inactive -> True/False. Giá trị khác -> None (chưa biết).

    Phân biệt "tắt" với "chưa biết" là cần thiết: xe không lắp cảm biến cửa mà hiển thị
    "cửa đóng" thì người xem tin vào một thứ không có thật.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text == 'active':
        return True
    if text == 'inactive':
        return False
    return None


def _as_text(value):
    """Chuỗi đã cắt khoảng trắng, hoặc None nếu rỗng."""
    if not isinstance(value, str):
        return None
    return value.strip() or None
