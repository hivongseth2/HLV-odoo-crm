"""Đọc file ghim xuất từ Google My Maps — hàm thuần, vào gì ra nấy.

Không đụng ``self.env``, không gọi mạng. Nhận chuỗi JSON, trả về list dict đã chuẩn hoá.

Định dạng nguồn (``map2.json``) dùng tên trường viết tắt::

    [{"f": "Tuyến Nhơn Trạch",      # lớp trên bản đồ — dùng để suy cụm tuyến
      "n": "JUNGWOO VINA",           # tên ghim
      "ad": "KCN Nhơn Trạch 2, ...", # địa chỉ
      "tx": "Kim Long",              # ghi chú tuyến / loại xe
      "gh": "hàng nhẹ",              # ghi chú hàng hoá
      "c": "10.74909,106.92426"}]    # toạ độ "lat,lng"

Toạ độ ở đây là do NGƯỜI ghim trên bản đồ và đã dùng chạy tuyến thật nhiều tháng, nên
đáng tin hơn kết quả máy tra — bên gọi nên lưu chúng ở trạng thái không cho máy đè lên.
"""

import json
import re

# Khung toạ độ Việt Nam, giống ``models/vtracking_address.py``. Ghim đặt nhầm chỗ trên bản
# đồ vẫn xuất ra một cặp số hợp lệ về cú pháp — chặn ở đây thì nó không lọt vào phép tính
# quãng đường và làm hỏng cả kế hoạch.
VN_LAT_MIN, VN_LAT_MAX = 8.0, 23.6
VN_LNG_MIN, VN_LNG_MAX = 102.0, 110.0


class MapImportError(Exception):
    """File không đọc được. Thông điệp nói rõ sai ở đâu để người dùng tự sửa."""


def parse_map_points(raw):
    """Chuỗi JSON -> list dict điểm đã chuẩn hoá.

    Mỗi phần tử trả về::

        {'layer', 'name', 'address', 'route_note', 'goods_note',
         'latitude', 'longitude', 'coords_error'}

    ``latitude``/``longitude`` là None khi ghim chưa có toạ độ (My Maps không xuất toạ độ
    cho ghim đặt theo địa chỉ) — điểm vẫn được trả về để còn tạo và tra toạ độ sau.
    ``coords_error`` nói vì sao toạ độ bị loại, rỗng nếu không có vấn đề.

    Ghim thiếu TÊN bị bỏ hẳn: không có gì để đặt tên địa điểm, và cũng không so trùng được.

    Ném ``MapImportError`` khi file không phải JSON, hoặc không phải một mảng.
    """
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise MapImportError('File không phải JSON hợp lệ: %s' % exc) from exc
    if not isinstance(data, list):
        raise MapImportError(
            'File phải là một mảng JSON các ghim. Nhận được: %s.' % type(data).__name__
        )

    points = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = (item.get('n') or '').strip()
        if not name:
            continue
        latitude, longitude, error = parse_coords(item.get('c'))
        points.append({
            'layer': (item.get('f') or '').strip(),
            'name': name,
            'address': (item.get('ad') or '').strip(),
            'route_note': (item.get('tx') or '').strip(),
            'goods_note': (item.get('gh') or '').strip(),
            'latitude': latitude,
            'longitude': longitude,
            'coords_error': error,
        })
    return points


def parse_coords(value):
    """Chuỗi "lat,lng" -> ``(lat, lng, error)``.

    Trả về ``(None, None, '')`` khi ghim không có toạ độ — đó là chuyện bình thường, không
    phải lỗi. Trả về lý do ở ``error`` khi có chuỗi nhưng không dùng được.
    """
    text = (value or '').strip()
    if not text:
        return None, None, ''
    parts = text.split(',')
    if len(parts) != 2:
        return None, None, 'Toạ độ "%s" không đúng dạng "lat,lng".' % text
    try:
        latitude = float(parts[0].strip())
        longitude = float(parts[1].strip())
    except ValueError:
        return None, None, 'Toạ độ "%s" không phải số.' % text
    if not (VN_LAT_MIN <= latitude <= VN_LAT_MAX and VN_LNG_MIN <= longitude <= VN_LNG_MAX):
        return None, None, (
            'Toạ độ (%s, %s) nằm ngoài Việt Nam — ghim đặt nhầm chỗ trên bản đồ.'
            % (latitude, longitude)
        )
    return latitude, longitude, ''


# Tỉ lệ từ của LỚP phải khớp tối thiểu chừng này thì mới nhận. Ngăn trường hợp một tên cụm
# ngắn lọt vào giữa một tên lớp dài: lớp "Chỉ đường từ Bến Đình, Vũng Tàu… đến Tôn Nam Kim
# Phú Mỹ" có chứa đúng chữ "Hồ Chí Minh" nhưng nó là lớp chỉ đường, không phải cụm tuyến.
MIN_LAYER_WORD_RATIO = 0.4

_WORD_RE = re.compile(r'[a-z0-9]+')

# Từ xuất hiện ở mọi tên lớp/cụm nên không phân biệt được gì, bỏ trước khi so.
_STOPWORDS = {'tuyen', 'router', 'khu', 'cong', 'nghiep', 'kcn', 'cum'}


def _words(value, strip_accents_fn):
    """Tập từ của một tên, đã bỏ dấu và bỏ từ vô nghĩa. Hàm phụ cho ``match_layer``."""
    text = strip_accents_fn(value or '').lower()
    return {word for word in _WORD_RE.findall(text) if word not in _STOPWORDS}


def match_layer(layer_name, zone_names, strip_accents_fn):
    """Ghép một lớp bản đồ với tên cụm tuyến. Trả về tên cụm, hoặc None.

    Ghép theo TỪ chứ không theo chuỗi con, vì hai lý do đã gặp thật:

    - Thứ tự từ khác nhau: lớp ghi "ROUTER TUYẾN BÌNH SƠN LONG THÀNH" còn cụm ghi
      "Long Thành – Bình Sơn". So chuỗi con thì trượt.
    - Mã cụm ngắn lọt vào chuỗi dài: mã "NT" nằm trong gần như mọi tên lớp, và từng gán
      nhầm cả lớp chỉ đường thành cụm Nhơn Trạch.

    Nhận khi **mọi từ của tên cụm đều có trong tên lớp**, VÀ số từ khớp chiếm đủ tỉ lệ
    trong tên lớp. Điều kiện thứ hai loại tên cụm ngắn lọt giữa một tên lớp dài.

    Nhiều cụm cùng đạt thì lấy cụm **nhiều từ nhất** — cụ thể hơn thì đúng hơn.
    ``strip_accents_fn`` truyền từ ngoài vào để file này không phải phụ thuộc addon khác.
    """
    layer_words = _words(layer_name, strip_accents_fn)
    if not layer_words:
        return None
    best, best_size = None, 0
    for zone_name in zone_names:
        zone_words = _words(zone_name, strip_accents_fn)
        if not zone_words or not zone_words <= layer_words:
            continue
        if len(zone_words) / len(layer_words) < MIN_LAYER_WORD_RATIO:
            continue
        if len(zone_words) > best_size:
            best, best_size = zone_name, len(zone_words)
    return best


def summarize(points):
    """Thống kê nhanh một lô điểm, để hiện trước khi người dùng bấm tạo.

    Trả về ``{'total', 'with_coords', 'without_coords', 'bad_coords', 'by_layer'}``.
    ``by_layer`` là list ``(tên lớp, số điểm)`` xếp theo số điểm giảm dần — lớp nào đông
    thì gần như chắc chắn là một cụm tuyến thật, lớp một hai điểm thường là ghi chú.
    """
    layers = {}
    for point in points:
        layers[point['layer']] = layers.get(point['layer'], 0) + 1
    return {
        'total': len(points),
        'with_coords': sum(1 for p in points if p['latitude'] is not None),
        'without_coords': sum(1 for p in points if p['latitude'] is None and not p['coords_error']),
        'bad_coords': sum(1 for p in points if p['coords_error']),
        'by_layer': sorted(layers.items(), key=lambda item: (-item[1], item[0])),
    }
