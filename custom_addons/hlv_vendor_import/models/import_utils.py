# -*- coding: utf-8 -*-
"""Quy tắc đọc file NCC: dò dòng tiêu đề, đề xuất vai trò cột, chuẩn hoá mã / số, xếp hạng sản phẩm
ứng viên. Util thuần: vào list / chuỗi, ra list / chuỗi — không đụng env.

Mỗi NCC một mẫu file (tiếng Việt, tiếng Anh, tiếng Trung, tiêu đề một hoặc hai tầng): ở đây chỉ ĐỀ XUẤT,
người bên mình sửa lại một lần trong mẫu của NCC đó.
"""

import re
import unicodedata

ROLE_CODE = "code"
ROLE_NAME = "name"
ROLE_NAME_ALT = "name_alt"
ROLE_UOM = "uom"
ROLE_STOCK = "stock"
ROLE_PRICE = "price"
ROLE_PRICE_INCL = "price_incl"
ROLE_VAT = "vat"
ROLE_IGNORE = "ignore"
ROLES = [
    (ROLE_CODE, "Mã hàng NCC"),
    (ROLE_NAME, "Tên hàng"),
    (ROLE_NAME_ALT, "Tên phụ / tên gốc"),
    (ROLE_UOM, "Đơn vị tính"),
    (ROLE_STOCK, "Số tồn (một kho)"),
    (ROLE_PRICE, "Đơn giá chưa VAT"),
    (ROLE_PRICE_INCL, "Đơn giá sau VAT"),
    (ROLE_VAT, "% VAT"),
    (ROLE_IGNORE, "Bỏ qua"),
]
PRICE_ROLES = (ROLE_PRICE, ROLE_PRICE_INCL)

# Thứ tự dò quan trọng: "主计量编码" (mã đơn vị tính) chứa cả "编码" (mã) — phải nhận ĐVT trước. Cột tồn xét
# trước cột giá (file tồn cũ có "giá trị tồn" vẫn đọc như trước). Cột giá ghi "chưa VAT" / "sau VAT" — xét giá sau
# VAT, rồi giá, rồi mới tới cột % VAT. Không ghi gì về VAT thì coi
# là giá chưa VAT (bảng giá NCC bán buôn hầu hết chưa VAT) — người dùng sửa ở bước xem lại cột nếu khác.
# Từ tiếng Việt / Anh so theo từ (đã bỏ dấu), từ tiếng Trung so theo chuỗi con.
_KEYWORDS = [
    (ROLE_UOM, ("dvt", "don vi", "don vi tinh", "unit", "uom"), ("计量", "单位")),
    (ROLE_STOCK, ("ton", "ton kho", "so luong", "sl", "qty", "quantity", "stock", "on hand", "kho"),
     ("结存", "库存", "数量", "仓")),
    (ROLE_PRICE_INCL, ("sau vat", "gom vat", "co vat", "da vat", "bao gom vat", "incl vat", "including vat"),
     ("含税",)),
    (ROLE_PRICE, ("gia", "don gia", "gia ban", "gny", "chua vat", "truoc vat", "price", "unit price", "excl vat"),
     ("未税", "价")),
    (ROLE_VAT, ("vat", "thue", "thue suat", "tax"), ("税率", "税")),
    (ROLE_CODE, ("ma", "ma hang", "ma sp", "code", "sku", "part no", "item no", "model"), ("编码", "编号", "型号")),
    (ROLE_NAME, ("ten", "ten hang", "name", "description", "dien giai", "mo ta"), ("名称", "品名", "规格")),
]
# Dòng cộng tổng cuối bảng — không phải mặt hàng.
_TOTAL_PREFIXES = ("tong", "total", "cong")
_TOTAL_CJK = ("合计", "总计")
_CJK = re.compile(r"[　-鿿＀-￯]")
_NOT_CJK_RUN = re.compile(r"[^　-鿿＀-￯]+")
CANDIDATE_LIMIT = 8
HEADER_MAX_LENGTH = 80
MIN_TERM_LENGTH = 4


def fold(text):
    """Chữ thường, bỏ dấu tiếng Việt (đ → d), gộp khoảng trắng. None → ""."""
    text = str(text or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def _keyword_role(header):
    """Vai trò đoán từ chữ của một tiêu đề, hoặc None khi không khớp từ khoá nào."""
    folded = fold(header)
    words = " %s " % re.sub(r"[^a-z0-9]+", " ", folded)
    for role, latin, cjk in _KEYWORDS:
        if any(" %s " % word in words for word in latin) or any(word in folded for word in cjk):
            return role
    return None


def parse_number(value):
    """Số từ một ô Excel.

    Nhận: số, chuỗi kiểu Việt ("1.234,5") hoặc Anh ("1,234.5"), có thể kèm chữ phía sau ("12 cái").
    Trả: float; ô trống, "-" hoặc không có số → None. Một dấu phân cách đi trước đúng 3 chữ số
    ("1.234" / "1,234") hiểu là phân cách nghìn — số tồn / số lượng NCC gửi hầu như luôn nguyên.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d[\d.,]*", str(value).replace(" ", ""))
    if not match:
        return None
    text = match.group(0).rstrip(".,")
    if "." in text and "," in text:
        decimal = "." if text.rfind(".") > text.rfind(",") else ","
        text = text.replace("," if decimal == "." else ".", "").replace(decimal, ".")
    elif text.count(".") + text.count(",") > 1 or re.search(r"[.,]\d{3}$", text):
        text = text.replace(".", "").replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def cell_text(value):
    """Ô Excel thành chuỗi: số nguyên dạng float (5304.0) → "5304", None → ""."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def column_letter(index):
    """Tên cột Excel từ chỉ số (từ 0): 0 → "A", 25 → "Z", 26 → "AA"."""
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def normalize_code(code):
    """Mã để so: chữ hoa, bỏ khoảng trắng và - _ . /. "SC 97813a" → "SC97813A"; None → ""."""
    return re.sub(r"[\s\-_./]", "", cell_text(code)).upper()


def split_prefixes(text):
    """"SC, HL" → ["SC", "HL"] (đã chuẩn hoá, dài trước để "SCA" được bỏ trước "SC"). Rỗng → []."""
    prefixes = {normalize_code(part) for part in (text or "").split(",")}
    return sorted((p for p in prefixes if p), key=len, reverse=True)


def code_key(code, prefixes):
    """Khoá mã NCC (bỏ tiền tố riêng của NCC): dùng để nhớ mã NCC → sản phẩm và dò ứng viên.

    "SC 97813A" với tiền tố ["SC"] → "97813A". Bỏ tiền tố mà không còn gì thì giữ nguyên mã.
    """
    code = normalize_code(code)
    for prefix in prefixes:
        if code.startswith(prefix) and len(code) > len(prefix):
            return code[len(prefix):]
    return code


CODE_SLOT = "{ma}"


def code_patterns(text, brand):
    """Mẫu mã bên mình của một NCC: mã bên mình viết thế nào từ khoá mã NCC (mã NCC đã bỏ tiền tố).

    Nhận: chữ người dùng khai — nhiều mẫu cách dấu phẩy / xuống dòng, mỗi mẫu có đúng một "{ma}" (vd SATA:
    "{ma}-SATA"; Makita: "{ma}"); hãng của NCC. Trả: list ``(phần trước, phần sau)`` đã chuẩn hoá như
    normalize_code (không phân biệt hoa thường, bỏ khoảng trắng - _ . /). Trống → mặc định "{ma}", "{ma}<hãng>",
    "<hãng>{ma}" (hãng trống thì chỉ "{ma}"). Mẫu không có đúng một "{ma}" bị bỏ.
    """
    parts = [part for part in re.split(r"[,\n]", text or "") if part.strip()]
    if not parts:
        brand_key = normalize_code(brand)
        return [("", "")] + ([("", brand_key), (brand_key, "")] if brand_key else [])
    patterns = []
    for part in parts:
        pieces = re.split(re.escape(CODE_SLOT), part, flags=re.IGNORECASE)
        if len(pieces) != 2:
            continue
        pattern = (normalize_code(pieces[0]), normalize_code(pieces[1]))
        if pattern not in patterns:
            patterns.append(pattern)
    return patterns


def our_codes(key, patterns):
    """Các mã bên mình (đã chuẩn hoá) có thể ứng với khoá mã NCC ``key`` theo ``patterns`` (code_patterns).

    "03200" với [("", "SATA")] → ["03200SATA"]. key rỗng → [].
    """
    return [before + key + after for before, after in patterns] if key else []


def keys_from_our_code(code, patterns):
    """Ngược our_codes: mã bên mình → các khoá mã NCC có thể, theo ``patterns``.

    "03200-SATA" với [("", "SATA"), ("", "")] → ["03200", "03200SATA"]. Mã trống / không khớp mẫu nào → [].
    """
    code = normalize_code(code)
    keys = []
    for before, after in patterns:
        if len(code) > len(before) + len(after) and code.startswith(before) and code.endswith(after):
            key = code[len(before):len(code) - len(after)]
            if key not in keys:
                keys.append(key)
    return keys


def looks_like_data(row):
    """Dòng có ô số (hoặc mã có số như "SC97813") không phải chữ Trung — là dòng dữ liệu, không phải dòng tiêu đề.

    Nhận: một dòng của lưới. Trả: bool; dòng rỗng → False.
    """
    return any(parse_number(cell) is not None and not _CJK.search(str(cell)) for cell in row if cell is not None)


def fix_two_tier(grid, header_row, header_rows):
    """Dòng tiêu đề hai tầng phải là số dòng của TẦNG TRÊN. Được cho tầng dưới (dòng ngay dưới đã là dữ liệu) thì lùi
    một dòng.

    Nhận: lưới; header_row (từ 1); header_rows (1|2). Trả: header_row đã sửa. Một tầng / dòng 1 / đúng sẵn → giữ nguyên.
    """
    if header_rows == 2 and header_row > 1 and header_row < len(grid) and looks_like_data(grid[header_row]):
        return header_row - 1
    return header_row


def detect_header(grid, scan=15):
    """Đoán dòng tiêu đề.

    Nhận: lưới (list dòng) đã điền ô gộp. Trả: ``(chỉ số dòng tiêu đề tính từ 0, số tầng 1|2)``.
    Dòng tiêu đề = dòng trong ``scan`` dòng đầu có nhiều tiêu đề khớp từ khoá nhất (hoà thì nhiều ô
    chữ hơn); ô gộp tính một lần, ô dài quá HEADER_MAX_LENGTH ký tự không tính. Tầng hai khi dòng ngay dưới toàn chữ, không có số, và có ô trùng ô phía trên (gộp dọc)
    hoặc phần lớn ô khớp từ khoá. Lưới rỗng → (0, 1).
    """
    best, best_score = 0, (-1, -1)
    for index, row in enumerate(grid[:scan]):
        # Ô gộp (đã điền vào mọi cột) đếm một lần; đoạn chữ dài là tiêu đề thư / ghi chú đầu file, không phải tên cột
        # — thông báo giá có cả đoạn "... điều chỉnh GIÁ ... mã số thuế" trải hết các cột.
        texts = {cell for cell in row if isinstance(cell, str) and len(cell) <= HEADER_MAX_LENGTH}
        score = (sum(1 for cell in texts if _keyword_role(cell)), len(texts))
        if score > best_score:
            best, best_score = index, score
    if best + 1 >= len(grid):
        return best, 1
    top, below = grid[best], grid[best + 1]
    cells = [cell for cell in below if cell is not None]
    if not cells or looks_like_data(below):
        return best, 1
    same = sum(1 for col, cell in enumerate(below) if cell is not None and col < len(top) and cell == top[col])
    hits = sum(1 for cell in cells if _keyword_role(cell))
    return best, (2 if same or hits * 2 >= len(cells) else 1)


def column_headers(grid, header_index, header_rows):
    """Tiêu đề từng cột (ghép "tầng trên / tầng dưới" khi hai tầng khác nhau).

    Nhận: lưới, chỉ số dòng tiêu đề (từ 0), số tầng. Trả: list chuỗi, bỏ các cột trống ở cuối.
    Dòng tiêu đề nằm ngoài lưới → [].
    """
    if header_index >= len(grid):
        return []
    rows = grid[header_index:header_index + header_rows]
    width = max(len(row) for row in rows)
    headers = []
    for col in range(width):
        parts = []
        for row in rows:
            text = cell_text(row[col]) if col < len(row) else ""
            if text and text not in parts:
                parts.append(text)
        headers.append(" / ".join(parts))
    while headers and not headers[-1]:
        headers.pop()
    return headers


def warehouse_label(header):
    """Tên kho cho một cột tồn: ưu tiên phần chữ Latin của tầng trên ("北宁仓库KHO BN / 结存数量" → "KHO BN").

    Không có phần Latin nào → cả tầng trên. Rỗng → "Tồn".
    """
    group = (header or "").split(" / ")[0].strip()
    runs = [run.strip(" -_/:") for run in _NOT_CJK_RUN.findall(group)]
    runs = [run for run in runs if re.search(r"[^\W\d_]", run)]
    return (max(runs, key=len) if runs else group) or "Tồn"


def propose_roles(headers):
    """Đề xuất vai trò cho từng cột.

    Nhận: list tiêu đề. Trả: list ``(vai trò, tên kho)`` cùng độ dài — tên kho chỉ có ở cột tồn, còn lại "".
    Cột tên thứ hai thành "tên phụ"; cột mã / ĐVT / giá / VAT thứ hai bị bỏ qua. Không có cột tồn nào khớp từ khoá
    thì giữ nguyên — người dùng chọn tay.
    """
    seen = set()
    roles = []
    for header in headers:
        role = _keyword_role(header) if header else None
        if role == ROLE_NAME and ROLE_NAME in seen:
            role = ROLE_NAME_ALT if ROLE_NAME_ALT not in seen else ROLE_IGNORE
        elif role in (ROLE_CODE, ROLE_UOM, ROLE_PRICE, ROLE_PRICE_INCL, ROLE_VAT) and role in seen:
            role = ROLE_IGNORE
        role = role or ROLE_IGNORE
        seen.add(role)
        roles.append((role, warehouse_label(header) if role == ROLE_STOCK else ""))
    return roles


def file_kinds(roles):
    """Loại dữ liệu một mẫu file mang: tập con của {"stock", "price"} — theo vai trò các cột.

    Nhận: các vai trò (chuỗi). Trả: frozenset; không có cột tồn lẫn cột giá → rỗng.
    """
    roles = set(roles)
    kinds = set()
    if ROLE_STOCK in roles:
        kinds.add("stock")
    if roles & set(PRICE_ROLES):
        kinds.add("price")
    return frozenset(kinds)


def read_vat(value, codes):
    """% VAT từ một ô Excel: 0.08 / 8 / "8%" → ("8", 8.0); "KCT" / "không chịu thuế" → ("kct", 0.0).

    Nhận: giá trị ô; ``codes`` — các mã VAT hợp lệ (vd ("0", "5", "8", "10", "kct")). Trả ``(mã, %)``; ô trống
    hay ra % không có trong ``codes`` (VAT lạ) → ("", None) — để chỗ dùng tự quyết.
    """
    folded = fold(cell_text(value))
    if folded in ("kct", "khong chiu thue", "khong chiu thue gtgt") and "kct" in codes:
        return "kct", 0.0
    number = parse_number(value)
    if number is None:
        return "", None
    if 0 < number < 1:
        number *= 100
    code = cell_text(round(number, 2))
    return (code, round(number, 2)) if code in codes else ("", None)


def price_pair(price, price_incl, rate):
    """Điền đơn giá còn thiếu từ đơn giá kia và % VAT.

    Nhận: đơn giá chưa VAT, đơn giá sau VAT (None / 0 = không có), % VAT (None = không biết).
    Trả: ``(chưa VAT, sau VAT)`` làm tròn 2 chữ số lẻ — giá không suy ra được (thiếu VAT) trả 0.0; cả hai
    cùng có thì giữ nguyên như file (NCC đã tính, không tính lại).
    """
    price, price_incl = price or 0.0, price_incl or 0.0
    if rate is not None:
        if price and not price_incl:
            price_incl = price * (1 + rate / 100.0)
        elif price_incl and not price:
            price = price_incl / (1 + rate / 100.0)
    return round(price, 2), round(price_incl, 2)


def header_signature(headers):
    """Vân tay mẫu file (tiêu đề đã bỏ dấu, nối bằng |) — NCC đổi cột là biết để đề xuất lại."""
    return "|".join(fold(header) for header in headers)


def _is_total(text):
    folded = fold(text)
    return folded.startswith(_TOTAL_PREFIXES) or any(word in text for word in _TOTAL_CJK)


def extract_rows(grid, first_row, columns, skip_group_rows=False):
    """Dòng hàng chuẩn từ lưới.

    Nhận: lưới; ``first_row`` — chỉ số dòng dữ liệu đầu tiên (từ 0); ``columns`` — list dict
    ``{"index", "role", "warehouse"}`` (index từ 0); ``skip_group_rows`` — bỏ dòng tiêu đề nhóm xen giữa bảng
    (không có ĐVT, không có số nào ở cột tồn / giá — vd "DỤNG CỤ CẦM TAY").
    Trả: list dict ``{"row" (số dòng Excel, từ 1), "code", "name", "name_alt", "uom", "stock": {kho: số},
    "price", "price_incl" (số hoặc None), "vat" (ô % VAT nguyên văn, None nếu không có)}``.
    Ô tồn trống tính 0 (file NCC để trống nghĩa là hết); ô giá trống là không có giá (None), không phải giá 0.
    Bỏ dòng không có cả mã lẫn tên, và dòng cộng tổng.
    """
    rows = []
    for index in range(first_row, len(grid)):
        cells = grid[index]
        values = {ROLE_CODE: "", ROLE_NAME: "", ROLE_NAME_ALT: "", ROLE_UOM: ""}
        stock = {}
        prices = {ROLE_PRICE: None, ROLE_PRICE_INCL: None, ROLE_VAT: None}
        has_number = False
        for column in columns:
            value = cells[column["index"]] if column["index"] < len(cells) else None
            if column["role"] in (ROLE_STOCK, ROLE_PRICE, ROLE_PRICE_INCL) and parse_number(value) is not None:
                has_number = True
            if column["role"] == ROLE_STOCK:
                label = column["warehouse"] or "Tồn"
                stock[label] = stock.get(label, 0.0) + (parse_number(value) or 0.0)
            elif column["role"] in prices and prices[column["role"]] is None:
                prices[column["role"]] = value if column["role"] == ROLE_VAT else parse_number(value)
            elif column["role"] in values and not values[column["role"]]:
                values[column["role"]] = cell_text(value)
        if not values[ROLE_CODE] and not values[ROLE_NAME]:
            continue
        if _is_total(values[ROLE_CODE] or values[ROLE_NAME]):
            continue
        if skip_group_rows and not values[ROLE_UOM] and not has_number:
            continue
        rows.append({"row": index + 1, "code": values[ROLE_CODE], "name": values[ROLE_NAME],
                     "name_alt": values[ROLE_NAME_ALT], "uom": values[ROLE_UOM], "stock": stock,
                     "price": prices[ROLE_PRICE], "price_incl": prices[ROLE_PRICE_INCL], "vat": prices[ROLE_VAT]})
    return rows


def stock_text(stock):
    """{"KHO BN": 97, "KHO BD": 0} → "KHO BN 97 · KHO BD 0"; {} → ""."""
    return " · ".join("%s %s" % (label, cell_text(float(qty))) for label, qty in stock.items())


def search_terms(code, name, prefixes):
    """Chuỗi dò sản phẩm ứng viên cho một dòng NCC — dò RỘNG, đúng sai để AI xét.

    Nhận: mã NCC, tên NCC, tiền tố của NCC. Trả: list chuỗi (không trùng, mỗi chuỗi ≥ 4 ký tự):
    mã gốc, khoá mã (bỏ tiền tố), khoá mã bỏ hậu tố chữ (biến thể "A", "S"… vẫn ra ứng viên),
    và mã model trong tên (từ có ≥ 3 chữ số, vd "AE5502"). Không có gì đủ dài → [].
    """
    key = code_key(code, prefixes)
    terms = [cell_text(code), key, re.sub(r"[A-Z]+$", "", key)]
    terms += [word for word in re.findall(r"[\w\-.]+", cell_text(name)) if len(re.findall(r"\d", word)) >= 3]
    result = []
    for term in terms:
        term = term.strip(" -.")
        if len(term) >= MIN_TERM_LENGTH and term.upper() not in {t.upper() for t in result}:
            result.append(term)
    return result


def rank_candidates(candidates, key, brand, limit=CANDIDATE_LIMIT):
    """Xếp ứng viên, giữ ``limit`` cái đầu.

    Nhận: list dict ``{"id", "code", "name"}``; khoá mã NCC (``code_key``); hãng của NCC (có thể rỗng).
    Trả: list đã xếp — mã bên mình chứa khoá mã trước, trùng hẳn (kể cả dạng "<khoá>-<HÃNG>") trước nữa,
    cùng hãng được cộng điểm. Không ứng viên → [].
    """
    brand_key = normalize_code(brand)
    brand_fold = fold(brand)
    digits = re.sub(r"\D", "", key)

    def score(candidate):
        ours = normalize_code(candidate.get("code"))
        points = 0
        if key and key in ours:
            points += 4
            if ours in (key, key + brand_key, brand_key + key):
                points += 2
        if digits and re.sub(r"\D", "", ours) == digits:
            points += 1
        if brand_fold and brand_fold in fold("%s %s" % (candidate.get("code") or "", candidate.get("name") or "")):
            points += 2
        return -points, candidate.get("code") or "", candidate["id"]

    return sorted(candidates, key=score)[:limit]
