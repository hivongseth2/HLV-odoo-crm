"""Dò bản ghi TRÙNG trong kho địa chỉ và danh sách địa điểm — hàm thuần, chỉ ĐỀ XUẤT.

Không đụng ``self.env``, không gộp gì. Trả về các nhóm nghi trùng kèm lý do và bản nên
giữ; việc gộp thật chỉ chạy trên đúng các id người (hoặc AI, sau khi người đồng ý) chỉ định.

**Không bao giờ coi hai bản ghi là trùng chỉ vì toạ độ gần nhau.** Geocoder gặp địa chỉ
KCN sơ sài hay trả về ĐÚNG MỘT tâm khu công nghiệp cho hàng chục công ty khác nhau — gộp
theo toạ độ là nhập các khách đó làm một. Toạ độ chỉ dùng để LOẠI: chữ giống mà hai điểm
cách xa nhau thì là hai lô khác nhau, không phải trùng.
"""

from odoo.addons.hlv_geo_utils.tools.geo_distance import haversine_km

from .vtracking_address import normalize_address

# Chữ chỉ cấp hành chính / loại đường. Sau đợt sáp nhập đơn vị hành chính 2025, cùng một
# địa chỉ xuất hiện dưới cả tên cũ lẫn tên mới ("Xã Long Thành, Tỉnh Đồng Nai" và "Phường
# Long Thành, Thành phố Đồng Nai") — phải bỏ các chữ này thì hai cách viết mới nhận ra nhau.
ADDRESS_STOPWORDS = frozenset((
    'viet', 'nam', 'vn', 'tinh', 'thanh', 'pho', 'tp', 'thi', 'tran', 'xa', 'phuong',
    'huyen', 'quan', 'duong', 'so', 'khu', 'cong', 'nghiep', 'kcn', 'ccn', 'cum', 'ap',
    'to', 'khom', 'lo', 'giai', 'doan', 'va', 'cua', 'the',
))

# Ngưỡng giống nhau (Jaccard trên tập chữ đã bỏ stopword). Đo trên các cặp đã biết trùng
# như 'Lô D, KCN Lộc An - Bình Sơn, Phường/Xã Long Thành...' ra 1.0; hai lô khác nhau
# trong cùng KCN thường dưới 0.6 vì số lô, tên đường khác.
ADDRESS_SIMILARITY = 0.75
# Chữ giống mà toạ độ cách hơn mức này thì là hai nơi khác nhau.
MAX_SPREAD_KM = 1.0
# Chữ xuất hiện ở quá nhiều địa chỉ ('dong', 'nai', 'nhon', 'trach'...) không dùng để
# ghép cặp ứng viên — không thì phải so gần như mọi cặp với nhau.
MAX_TOKEN_DF = 40

GEO_RANK = {'manual': 0, 'confirmed': 1, 'pending_review': 2, 'none': 3, 'failed': 4}


def address_tokens(raw_address):
    """Tập chữ đặc trưng của một địa chỉ: đã chuẩn hoá, bỏ dấu, bỏ chữ hành chính."""
    text = normalize_address(raw_address or '')
    words = ''.join(char if char.isalnum() else ' ' for char in text).split()
    return frozenset(word for word in words if word not in ADDRESS_STOPWORDS)


def identifier_tokens(tokens):
    """Chữ ĐỊNH DANH một địa điểm cụ thể: số nhà, số lô, số đường — chữ có chứa số, hoặc
    chỉ một ký tự ("lô D" -> "d").

    Vì sao tách riêng: "Lô D" và "Lô N" trong cùng KCN giống nhau ~0.8 theo Jaccard vì mọi
    chữ khác đều chung — nhưng đó là hai công ty. Thứ phân biệt chúng chỉ là một ký tự.
    """
    return frozenset(token for token in tokens if len(token) == 1 or any(c.isdigit() for c in token))


def jaccard(tokens_a, tokens_b):
    """Độ giống của hai tập chữ, 0..1. Hai tập rỗng coi là 0 — không có gì để khẳng định."""
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / float(len(tokens_a | tokens_b))


def _near(point_a, point_b, max_km):
    """Không đo được (thiếu toạ độ) thì coi như không bác bỏ — chữ quyết định."""
    if not (point_a and point_b):
        return True
    distance = haversine_km(point_a, point_b)
    return distance is None or distance <= max_km


def _groups(ids, pairs):
    """Union-find: các cặp nối nhau -> nhóm id, chỉ trả nhóm từ 2 phần tử."""
    parent = {item: item for item in ids}

    def root(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for first, second in pairs:
        parent[root(first)] = root(second)
    grouped = {}
    for item in ids:
        grouped.setdefault(root(item), []).append(item)
    return [sorted(members) for members in grouped.values() if len(members) > 1]


def address_duplicate_groups(rows, similarity=ADDRESS_SIMILARITY):
    """Nhóm địa chỉ nghi trùng.

    rows: list dict ``{'id', 'raw_address', 'point': (lat, lng)|None, 'geo_state',
        'hit_count'}``.

    Trả về list ``{'ids': [...], 'keep_id': int, 'score': float}``, nhóm điểm cao đứng
    trước. ``keep_id``: bản có toạ độ đáng tin nhất (nhập tay > đã duyệt > máy tra), hoà thì
    bản được dùng lại nhiều hơn — nó đang là thứ các phiếu trỏ tới.
    """
    by_id = {row['id']: dict(row, tokens=address_tokens(row['raw_address'])) for row in rows}
    index = {}
    for row in by_id.values():
        for token in row['tokens']:
            index.setdefault(token, []).append(row['id'])

    pairs, scores = set(), {}
    for members in index.values():
        if len(members) > MAX_TOKEN_DF:
            continue
        for pos, first in enumerate(members):
            for second in members[pos + 1:]:
                pair = (min(first, second), max(first, second))
                if pair in scores:
                    continue
                a, b = by_id[pair[0]], by_id[pair[1]]
                score = jaccard(a['tokens'], b['tokens'])
                scores[pair] = score
                # Bộ định danh phải GIỐNG HỆT — kể cả khi một bên có số lô còn bên kia
                # không có: không biết thì không gộp. Bỏ sót một cặp trùng chỉ tốn một lần
                # tra toạ độ; gộp nhầm là hai khách thành một điểm giao.
                same_identity = identifier_tokens(a['tokens']) == identifier_tokens(b['tokens'])
                if (score >= similarity and same_identity
                        and _near(a['point'], b['point'], MAX_SPREAD_KM)):
                    pairs.add(pair)

    result = []
    for ids in _groups(list(by_id), pairs):
        members = [by_id[item] for item in ids]
        keep = min(members, key=lambda row: (
            GEO_RANK.get(row.get('geo_state'), 9), -(row.get('hit_count') or 0), row['id'],
        ))
        best = max((scores.get((min(x, y), max(x, y)), 0.0)
                    for x in ids for y in ids if x < y), default=0.0)
        result.append({'ids': ids, 'keep_id': keep['id'], 'score': round(best, 2)})
    result.sort(key=lambda group: (-group['score'], group['ids'][0]))
    return result


def place_duplicate_groups(rows, near_km=0.05):
    """Nhóm địa điểm nghi trùng, kèm LÝ DO — vì có lý do là trùng thật, có lý do chỉ là nghi.

    rows: list dict ``{'id', 'name_key', 'root_partner_id': int|None, 'point', 'geo_state',
        'has_profile': bool, 'has_warehouse': bool}``. ``name_key``: tên đã chuẩn hoá
        (``hlv_geo_utils.normalize_name``).

    Lý do:
      * ``same_customer`` — cùng pháp nhân gốc. Dòng kế hoạch chỉ ghép được với MỘT điểm
        của khách (``limit=1``), nên điểm thứ hai không bao giờ được dùng. Nhưng một khách
        CÓ THỂ có hai nhà máy thật — nên đây là nghi, người phải xem.
      * ``same_name`` — tên chuẩn hoá trùng nhau.
      * ``same_spot`` — cách dưới ``near_km`` VÀ tên giống một phần. Chỉ gần nhau thôi
        không đủ (xem ghi chú đầu file).

    Trả về list ``{'ids', 'keep_id', 'reasons'}``. ``keep_id``: bản đang có thói quen khách,
    gắn kho, toạ độ đáng tin — thứ tự đó, vì mất thói quen khách là mất công người điền.
    """
    reasons_by_pair = {}

    def add(first, second, reason):
        pair = (min(first, second), max(first, second))
        reasons_by_pair.setdefault(pair, set()).add(reason)

    by_root, by_name = {}, {}
    for row in rows:
        if row.get('root_partner_id'):
            by_root.setdefault(row['root_partner_id'], []).append(row['id'])
        if row.get('name_key'):
            by_name.setdefault(row['name_key'], []).append(row['id'])
    for bucket, reason in ((by_root, 'same_customer'), (by_name, 'same_name')):
        for members in bucket.values():
            for pos, first in enumerate(members):
                for second in members[pos + 1:]:
                    add(first, second, reason)

    located = [row for row in rows if row.get('point')]
    for pos, first in enumerate(located):
        for second in located[pos + 1:]:
            distance = haversine_km(first['point'], second['point'])
            if distance is None or distance > near_km:
                continue
            key_a, key_b = first.get('name_key') or '', second.get('name_key') or ''
            if key_a and key_b and (key_a in key_b or key_b in key_a):
                add(first['id'], second['id'], 'same_spot')

    by_id = {row['id']: row for row in rows}
    result = []
    for ids in _groups(list(by_id), reasons_by_pair):
        members = [by_id[item] for item in ids]
        keep = min(members, key=lambda row: (
            not row.get('has_profile'), not row.get('has_warehouse'),
            GEO_RANK.get(row.get('geo_state'), 9), row['id'],
        ))
        reasons = set()
        for pair, found in reasons_by_pair.items():
            if pair[0] in ids:
                reasons |= found
        result.append({'ids': ids, 'keep_id': keep['id'], 'reasons': sorted(reasons)})
    result.sort(key=lambda group: group['ids'][0])
    return result
