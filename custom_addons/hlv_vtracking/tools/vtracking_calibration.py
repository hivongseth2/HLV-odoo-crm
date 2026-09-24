"""Học lại định mức cụm từ chuyến đã chạy — hàm thuần, vào gì ra nấy.

Không đụng ``self.env``, không ghi gì. Nhận các chuyến đã có số thực tế, trả về mẫu đo và
đề xuất. Việc đọc dữ liệu từ Odoo và ghi đề xuất lên cụm nằm ở
``services/vtracking_calibration.py``.

**Chỉ ĐỀ XUẤT, không tự ghi đè định mức.** Vài ngày kẹt xe, một tài xế mới, hay một đợt
hàng cồng kềnh là đủ kéo lệch trung vị mà không ai hay — rồi mọi kế hoạch sau đó lệch
theo. Người điều phối nhìn đề xuất kèm số mẫu rồi bấm áp dụng.

Ba loại mẫu, khớp đúng ba định mức của cụm:

* ``hub``    kho -> điểm giao ĐẦU TIÊN: từ lúc shipper quét nhận hàng tới lúc giao xong
             điểm đầu. Chỉ lấy khi mốc xuất phát là lúc quét nhận (không phải lùi về lúc
             giao xong) — lùi như vậy thì chặng đầu thành 0.
* ``leg``    điểm -> điểm TRONG CÙNG một cụm: giữa hai lần giao xong liên tiếp. Chặng vượt
             cụm bỏ qua — nó không thuộc về định mức của cụm nào.
* ``return`` điểm cuối -> về kho: từ lúc giao xong điểm cuối tới lúc GPS thấy xe quay lại
             gần điểm xuất phát.

Mốc là lúc GIAO XONG (``date_done`` của phiếu) — đúng mốc mà định mức cụm được đo từ đầu,
nên mỗi mẫu ``leg`` đã gồm cả bốc dỡ và ký nhận tại điểm, khớp cách ``vtracking_route``
dùng ``median_leg_minutes``.
"""

from odoo.addons.hlv_geo_utils.tools.geo_distance import haversine_km

from .vtracking_actual import minutes_between
from .vtracking_route import same_point

# Ngoài khoảng này là dữ liệu hỏng chứ không phải chuyến chậm: phiếu bấm xong bù cuối ngày,
# hai phiếu bấm cùng một giây, xe về kho giữa chuyến lấy thêm hàng...
MIN_SAMPLE_MINUTES = 1
MAX_SAMPLE_MINUTES = 240

# Dưới số mẫu này thì trung vị chưa đủ tin để đề xuất. 10 chặng ≈ 2 chuyến của một cụm.
MIN_SAMPLES = 10

# Lệch dưới mức này so với định mức hiện tại thì không coi là đề xuất — tránh bắt người
# điều phối bấm áp dụng cho những thay đổi 1 phút vô nghĩa.
MIN_CHANGE_MINUTES = 2

# --- BẤM GỘP -----------------------------------------------------------------------
# Tài xế không dùng app thì kho bấm xong một loạt phiếu sau khi xe đã về: nhiều điểm cách
# nhau nhiều cây số mang cùng một dấu thời gian đến từng phút. Đo trên chính kho này: 23%
# phiếu xuất trong hai tháng bị bấm kiểu đó. Lấy các mốc ấy làm mẫu thì trung vị tụt xuống
# gần 0 và định mức học được sẽ sai.
#
# Lớp chặn THỨ NHẤT nằm ở ``services/vtracking_calibration``: chỉ nhận điểm có giờ do
# shipper QUÉT (``barcode.scan.log``), bỏ hết giờ bấm trong Odoo. Phần dưới đây là lớp thứ
# hai, cho trường hợp chính cái máy quét bị dùng để quét gộp cả xấp phiếu lúc xe đã về.
#
# Dấu hiệu là VẬN TỐC SUY RA: hai điểm cách 8 km mà cách nhau 1 phút thì không phải xe chạy
# nhanh, mà là người bấm nhanh.
GROUPED_CLICK_MINUTES = 2
MAX_IMPLIED_KMH = 70
# Thiếu toạ độ thì không suy được vận tốc; lúc đó cần một CHUỖI dài mới dám kết luận, vì
# hai điểm liền nhau cách nhau 2 phút hoàn toàn có thể là hai khách cạnh nhau trong một KCN.
MIN_BATCH_POINTS = 3

KINDS = ('hub', 'leg', 'return')


def _usable(minutes):
    return minutes is not None and MIN_SAMPLE_MINUTES <= minutes <= MAX_SAMPLE_MINUTES


def implied_kmh(km, minutes):
    """Vận tốc suy ra từ quãng đường và thời gian. None khi không tính được.

    Quãng đường là đường chim bay nên vận tốc suy ra luôn THẤP hơn thực tế — càng chắc
    chắn khi nó vẫn vượt ngưỡng: đường thật còn dài hơn thế.
    """
    if km is None or not minutes or minutes <= 0:
        return None
    return km / (minutes / 60.0)


def clerical_flags(points, gap_minutes=GROUPED_CLICK_MINUTES,
                   max_kmh=MAX_IMPLIED_KMH, min_batch=MIN_BATCH_POINTS):
    """Điểm nào có dấu thời gian do BẤM GỘP mà ra. Hàm thuần.

    :param points: list dict ``{'delivered_at', 'point'}`` đã sắp theo giờ giao
    :returns: list bool cùng độ dài — True nghĩa là mốc giờ của điểm đó không đáng tin

    Hai đường nhận biết:
      * cặp liền nhau cách nhau ``gap_minutes`` phút mà vận tốc suy ra vượt ``max_kmh``;
      * chuỗi từ ``min_batch`` điểm trở lên mà mọi khoảng cách đều dưới ``gap_minutes``
        phút — dùng khi thiếu toạ độ, lúc đó không suy được vận tốc.
    """
    flags = [False] * len(points)
    if len(points) < 2:
        return flags

    gaps = []
    for index, (before, after) in enumerate(zip(points, points[1:])):
        minutes = minutes_between(before['delivered_at'], after['delivered_at'])
        close = minutes is not None and minutes <= gap_minutes
        gaps.append(close)
        if not close:
            continue
        speed = implied_kmh(haversine_km(before.get('point'), after.get('point')), minutes)
        if speed is not None and speed > max_kmh:
            flags[index] = flags[index + 1] = True

    # Chuỗi dài các mốc sát nhau: đánh dấu cả chuỗi.
    run = 0
    for index, close in enumerate(gaps + [False]):
        if close:
            run += 1
            continue
        if run + 1 >= min_batch:
            for position in range(index - run, index + 1):
                flags[position] = True
        run = 0
    return flags


def trip_samples(start_at, start_is_scan, stops, back_at=None):
    """Mẫu đo của MỘT chuyến.

    start_at: lúc xe xuất phát (datetime) hoặc None.
    start_is_scan: True khi ``start_at`` là lúc shipper quét nhận hàng — chỉ khi đó mới lấy
        được mẫu ``hub``.
    stops: list dict các điểm ĐÃ GIAO XONG, mỗi phần tử
        ``{'delivered_at': datetime, 'zone_id': int|None, 'point': (lat, lng)|None,
        'key': hashable|None}``. Thứ tự không quan trọng — sắp lại theo giờ giao THẬT,
        vì tài xế không nhất thiết đi đúng thứ tự trên kế hoạch.
    back_at: lúc xe về tới kho (từ GPS), hoặc None.

    Trả về list tuple ``(kind, zone_id, minutes)``. Nhiều đơn liền nhau cùng một chỗ gộp
    thành một điểm (``same_point``) — không thì mỗi đơn thêm là một mẫu ``leg`` ~0 phút,
    kéo trung vị tụt xuống.
    """
    ordered = sorted(
        (stop for stop in stops if stop.get('delivered_at')),
        key=lambda stop: stop['delivered_at'],
    )
    points = []
    for stop in ordered:
        if points and same_point(points[-1]['point'], stop['point'],
                                 points[-1]['key'], stop['key']):
            # Giữ lúc giao xong ĐƠN CUỐI tại điểm đó: xe chỉ rời đi sau khi xong hết.
            points[-1] = dict(points[-1], delivered_at=stop['delivered_at'])
            continue
        points.append(stop)
    if not points:
        return []

    # Mốc do bấm gộp không phải giờ xe tới: bỏ hẳn, đừng đưa vào bất kỳ loại mẫu nào.
    clerical = clerical_flags(points)

    samples = []
    first = points[0]
    if start_is_scan and first.get('zone_id') and not clerical[0]:
        minutes = minutes_between(start_at, first['delivered_at'])
        if _usable(minutes):
            samples.append(('hub', first['zone_id'], minutes))

    for index, (before, after) in enumerate(zip(points, points[1:])):
        zone_id = after.get('zone_id')
        if not zone_id or zone_id != before.get('zone_id'):
            continue
        if clerical[index] or clerical[index + 1]:
            continue
        minutes = minutes_between(before['delivered_at'], after['delivered_at'])
        if _usable(minutes):
            samples.append(('leg', zone_id, minutes))

    last = points[-1]
    if back_at and last.get('zone_id') and not clerical[-1]:
        minutes = minutes_between(last['delivered_at'], back_at)
        if _usable(minutes):
            samples.append(('return', last['zone_id'], minutes))
    return samples


def median(values):
    """Trung vị, làm tròn phút. List rỗng trả về None.

    Dùng trung vị chứ không dùng trung bình: một chuyến kẹt xe 3 tiếng kéo trung bình lên
    cả chục phút, còn trung vị gần như không nhúc nhích.
    """
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return int(round(ordered[middle]))
    return int(round((ordered[middle - 1] + ordered[middle]) / 2.0))


def suggestions(samples, current, min_samples=MIN_SAMPLES):
    """Gom mẫu theo cụm và loại, ra đề xuất cho từng cụm.

    samples: list tuple ``(kind, zone_id, minutes)`` từ nhiều chuyến.
    current: dict ``{zone_id: {'hub': int, 'leg': int, 'return': int}}`` — định mức đang dùng.

    Trả về ``{zone_id: {kind: {'median', 'count', 'current', 'suggest'}}}``. ``suggest`` là
    None khi chưa đủ mẫu hoặc lệch dưới ``MIN_CHANGE_MINUTES`` — khi đó ``median`` và
    ``count`` vẫn có để người xem biết đã đo được gì.
    """
    grouped = {}
    for kind, zone_id, minutes in samples:
        grouped.setdefault(zone_id, {}).setdefault(kind, []).append(minutes)

    result = {}
    for zone_id, by_kind in grouped.items():
        result[zone_id] = {}
        for kind in KINDS:
            values = by_kind.get(kind, [])
            value = median(values)
            now = (current.get(zone_id) or {}).get(kind)
            enough = len(values) >= min_samples
            changed = value is not None and (now is None or abs(value - now) >= MIN_CHANGE_MINUTES)
            result[zone_id][kind] = {
                'median': value,
                'count': len(values),
                'current': now,
                'suggest': value if (enough and changed) else None,
            }
    return result


def log_rows(by_kind):
    """Kết quả của ``suggestions`` cho MỘT cụm -> các dòng nhật ký hiệu chỉnh.

    by_kind: ``{kind: {'median', 'count', 'current', 'suggest'}}`` (có thể rỗng).

    Trả về list dict ``{'kind', 'norm_minutes', 'measured_minutes', 'suggest_minutes',
    'sample_count'}`` theo thứ tự ``KINDS``. Loại chưa có mẫu nào thì bỏ — một dòng "0 mẫu"
    mỗi ngày chỉ làm nhật ký dài ra mà không nói gì. Chưa có đề xuất thì ``suggest_minutes``
    là 0.
    """
    rows = []
    for kind in KINDS:
        item = by_kind.get(kind) or {}
        if not item.get('count'):
            continue
        rows.append({
            'kind': kind,
            'norm_minutes': item.get('current') or 0,
            'measured_minutes': item.get('median') or 0,
            'suggest_minutes': item.get('suggest') or 0,
            'sample_count': item['count'],
        })
    return rows
