# -*- coding: utf-8 -*-
"""Hàm thuần cho báo giá NCC — không đụng env, không side effect."""

import hashlib
import re
from datetime import datetime, timedelta

import pytz

_CURRENCY_SUFFIX = re.compile(r"(vn)?[dđ]$", re.IGNORECASE)
LOCAL_TZ = "Asia/Ho_Chi_Minh"
DATE_FMT = "%d/%m/%Y"
DATETIME_FMT = "%H:%M %d/%m/%Y"


def local_date_text(value, fmt=DATE_FMT):
    """Ngày / giờ để hiện cho người Việt Nam đọc.

    value: datetime naive theo UTC (đúng kiểu Odoo lưu Datetime) → đổi sang giờ Việt Nam rồi
    định dạng — in thẳng thì 00:00 ngày 08 giờ VN ra ngày 07; date (Field Date, không có giờ)
    → định dạng giữ nguyên ngày; None / False / rỗng → "".
    """
    if not value:
        return ""
    if isinstance(value, datetime):
        value = pytz.utc.localize(value).astimezone(pytz.timezone(LOCAL_TZ))
    return value.strftime(fmt)


def parse_vn_number(text):
    """Đọc con số NCC gõ tay theo thói quen Việt Nam.

    Nhận: chuỗi bất kỳ, ví dụ "1.250.000", "1,250,000", "1.250.000,5", "12,5",
    "3 000", "150000đ".
    Trả: float >= 0, hoặc None khi rỗng / không phải số.

    Bẫy: "1.250" và "1,250" đọc là 1250 chứ không phải 1,25 — một dấu duy nhất mà
    đứng trước đúng 3 chữ số được coi là phân cách nghìn, vì giá VND hầu như không
    có phần lẻ 3 chữ số. Có cả chấm lẫn phẩy thì dấu xuất hiện sau cùng là dấu thập
    phân ("1.250.000,5" → 1250000.5).
    """
    s = str(text or "").strip().replace(" ", "").replace(" ", "")
    s = _CURRENCY_SUFFIX.sub("", s)
    if not s or not re.fullmatch(r"[0-9.,]+", s) or not re.search(r"[0-9]", s):
        return None

    separators = set(re.findall(r"[.,]", s))
    if not separators:
        return float(s)

    if len(separators) == 2:
        decimal_sep = s[max(s.rfind("."), s.rfind(","))]
        if s.count(decimal_sep) > 1:
            return None
        thousand_sep = "," if decimal_sep == "." else "."
        integer_part, decimal_part = s.replace(thousand_sep, "").split(decimal_sep)
        return float(f"{integer_part or 0}.{decimal_part or 0}")

    sep = separators.pop()
    parts = s.split(sep)
    if len(parts) > 2:
        if not (1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:])):
            return None
        return float("".join(parts))
    integer_part, tail = parts
    if len(tail) == 3 and integer_part:
        return float(integer_part + tail)
    return float(f"{integer_part or 0}.{tail or 0}")


def format_vn_number(value):
    """Viết số theo kiểu Việt Nam để điền sẵn vào ô nhập.

    Nhận: số (int/float) hoặc None/False.
    Trả: chuỗi chấm phân cách nghìn, phẩy thập phân, tối đa 2 chữ số lẻ, bỏ số 0
    thừa: 1250000 → "1.250.000", 1250.5 → "1.250,5". None/False → "".
    Đọc lại bằng parse_vn_number cho đúng giá trị (đã làm tròn 2 chữ số lẻ).
    """
    if value is None or value is False:
        return ""
    integer_part, decimal_part = f"{value:,.2f}".split(".")
    decimal_part = decimal_part.rstrip("0")
    integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part}" if decimal_part else integer_part


_EMAIL_RE = re.compile(r"[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+")


def parse_email_list(text):
    """Ô "gửi tới" sale gõ → (email hợp lệ, phần không phải email).

    text: chuỗi, các địa chỉ cách nhau bằng dấu phẩy, chấm phẩy, khoảng trắng hoặc xuống dòng.
    Trả hai list theo thứ tự gõ; email hợp lệ đã bỏ trùng (không phân biệt hoa thường) và
    viết thường. None / rỗng → ([], []).
    """
    valid, invalid, seen = [], [], set()
    for part in re.split(r"[,;\s]+", text or ""):
        if not part:
            continue
        if not _EMAIL_RE.fullmatch(part):
            invalid.append(part)
            continue
        email = part.lower()
        if email not in seen:
            seen.add(email)
            valid.append(email)
    return valid, invalid


def requester_text(name, phone):
    """Người hỏi giá hiện cho NCC: "Trâm Bến Cam – 0983300122".

    name, phone: chuỗi (None coi như rỗng). Thiếu một trong hai → phần còn lại; thiếu cả hai → "".
    """
    return " – ".join(part.strip() for part in (name or "", phone or "") if part and part.strip())


def split_code_name(name, code):
    """Tên hàng bỏ tiền tố mã, để hiện mã và tên thành hai cột riêng.

    name: tên dòng, có thể dạng "[MÃ] Tên" (display_name của Odoo); code: mã hàng hoặc rỗng.
    Trả tên đã bỏ "[code]" ở đầu và khoảng trắng thừa. Không có mã / không có tiền tố → tên
    nguyên (đã strip); bỏ tiền tố mà hết chữ → giữ tên nguyên. None → "".
    """
    name = (name or "").strip()
    prefix = f"[{code}]" if code else ""
    if prefix and name.startswith(prefix):
        return name[len(prefix):].strip() or name
    return name


def resolve_net_price(price, gross, tax_rate, list_price, discount):
    """Đơn giá chưa VAT (đã trừ chiết khấu) của một dòng NCC gửi — giá lưu và đem so.

    Nhận các số đã đọc từ form (None khi ô trống): price = đơn giá chưa VAT; gross = đơn giá
    sau VAT; tax_rate = % VAT (0 khi không chịu thuế / chưa chọn); list_price = đơn giá trước
    chiết khấu; discount = % chiết khấu (None = không dùng chiết khấu).
    Trả float làm tròn 2 chữ số lẻ, hoặc None khi không suy ra được.

    Ưu tiên price: trang có JS đã tính sẵn cả ba ô, lấy thẳng ô này để khỏi lệch vì làm tròn
    hai lần. Chỉ khi price trống (JS hỏng / NCC tắt JS) mới suy từ gross, rồi từ list_price.
    """
    if price:
        return round(price, 2)
    if gross:
        return round(gross / (1 + (tax_rate or 0) / 100.0), 2)
    if list_price:
        return round(list_price * (1 - (discount or 0) / 100.0), 2)
    return None


def session_fingerprint(token, password):
    """Dấu vân tay của một lần đăng nhập link báo giá.

    Nhận: mã link và mật khẩu hiện tại (chuỗi; None coi như rỗng).
    Trả: chuỗi hex sha256. Đổi mã link hoặc mật khẩu thì dấu vân tay đổi, nên mọi
    phiên đã đăng nhập trước đó tự hết hiệu lực.
    """
    raw = f"{token or ''}\0{password or ''}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def next_failed_count(failed_count, last_failed_at, now, lock_minutes):
    """Số lần sai mật khẩu sau khi ghi nhận thêm một lần sai.

    Nhận: số lần sai đang lưu, thời điểm sai gần nhất (datetime hoặc None), lúc này,
    độ dài cửa sổ khoá (phút).
    Trả: int. Lần sai trước đã cũ hơn cửa sổ khoá thì đếm lại từ 1 — để NCC gõ sai
    vài lần hôm trước không bị khoá ngay ở lần sai đầu tiên hôm sau.
    """
    if not last_failed_at or now - last_failed_at > timedelta(minutes=lock_minutes):
        return 1
    return (failed_count or 0) + 1


def is_login_locked(failed_count, last_failed_at, now, max_attempts, lock_minutes):
    """Link có đang bị khoá đăng nhập không.

    Nhận: số lần sai, thời điểm sai gần nhất (datetime hoặc None), lúc này, số lần
    sai tối đa, độ dài khoá (phút).
    Trả: True khi đã sai đủ max_attempts lần và lần sai cuối chưa quá lock_minutes.
    Chưa từng sai (None) → False.
    """
    if not last_failed_at or (failed_count or 0) < max_attempts:
        return False
    return now - last_failed_at <= timedelta(minutes=lock_minutes)


def best_price_ids(offers):
    """Tìm các báo giá rẻ nhất cho từng mặt hàng.

    Nhận: iterable các bộ (offer_id, group_key, price) — group_key là mặt hàng
    đang so (dòng YCMH), price là đơn giá chưa VAT.
    Trả: set offer_id có giá thấp nhất trong nhóm; hoà giá thì lấy hết. Bỏ qua giá
    None hoặc <= 0 (NCC chưa báo / không cung cấp). Không có gì → set().
    """
    best = {}
    for offer_id, group_key, price in offers:
        if not price or price <= 0:
            continue
        current = best.get(group_key)
        if current is None or price < current[0]:
            best[group_key] = (price, {offer_id})
        elif price == current[0]:
            current[1].add(offer_id)
    return {offer_id for _price, ids in best.values() for offer_id in ids}


def paginate(total, page, per_page):
    """Tính phân trang cho danh sách.

    Nhận: tổng số bản ghi, số trang người dùng yêu cầu (int/chuỗi/None, đếm từ 1),
    số bản ghi mỗi trang (> 0).
    Trả: dict {"page", "page_count", "offset", "limit"}. Trang không hợp lệ hoặc
    vượt quá thì kẹp về khoảng [1, page_count]; total = 0 vẫn trả page_count = 1.
    """
    page_count = max(1, -(-int(total) // per_page))
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    page = min(max(page, 1), page_count)
    return {
        "page": page,
        "page_count": page_count,
        "offset": (page - 1) * per_page,
        "limit": per_page,
    }


def match_by_product(items, candidates):
    """Ghép một-một dòng báo giá với dòng YCMH theo sản phẩm, giữ thứ tự.

    Nhận: items là iterable (item_id, product_id) cần ghép; candidates là iterable
    (candidate_id, product_id) còn trống. Cả hai theo thứ tự hiển thị.
    Trả: dict {item_id: candidate_id}. Item không còn candidate cùng sản phẩm thì
    không có trong dict; mỗi candidate dùng tối đa một lần (YCMH có 2 dòng cùng mã
    thì 2 dòng báo giá cùng mã ghép lần lượt vào từng dòng).
    """
    free = {}
    for candidate_id, product_id in candidates:
        free.setdefault(product_id, []).append(candidate_id)
    matched = {}
    for item_id, product_id in items:
        if free.get(product_id):
            matched[item_id] = free[product_id].pop(0)
    return matched


def rank_vendor_suggestions(coverage, order_stats, limit):
    """Xếp hạng NCC nên hỏi giá cho một nhóm sản phẩm.

    Nhận:
    - coverage: iterable (partner_id, product_id, source) — source "po" là NCC đã từng
      bán sản phẩm đó cho mình, "pricelist" là NCC có trong bảng giá NCC của sản phẩm.
    - order_stats: dict partner_id → (số đơn mua đã xác nhận, ngày mua gần nhất hoặc None).
    - limit: số NCC tối đa trả về.
    Trả: list dict {partner_id, product_ids (set), from_pricelist (bool), order_count,
    last_date}, xếp: phủ nhiều mặt hàng hơn → mua nhiều đơn hơn → mua gần đây hơn.
    Không có dữ liệu → [].
    """
    vendors = {}
    for partner_id, product_id, source in coverage:
        vendor = vendors.setdefault(partner_id, {
            "partner_id": partner_id,
            "product_ids": set(),
            "from_pricelist": False,
        })
        vendor["product_ids"].add(product_id)
        if source == "pricelist":
            vendor["from_pricelist"] = True
    for vendor in vendors.values():
        vendor["order_count"], vendor["last_date"] = order_stats.get(vendor["partner_id"], (0, None))

    def sort_key(vendor):
        last = vendor["last_date"]
        return (-len(vendor["product_ids"]), -vendor["order_count"], -(last.toordinal() if last else 0))

    return sorted(vendors.values(), key=sort_key)[:limit]


def build_share_message(company_name, vendor_name, quote_names, deadline_text, url, password, reask=(), requester=""):
    """Tin nhắn sale dán vào Zalo gửi NCC — gọn: số báo giá, hạn, link chung của NCC, mật khẩu.

    Nhận: tên công ty mình, tên NCC, list số báo giá, hạn báo giá đã định dạng ("" nếu
    không có hạn), link chung của NCC, mật khẩu (chuỗi; rỗng = đang tắt mật khẩu, bỏ dòng
    mật khẩu), requester: "Tên – SĐT" người hỏi giá (rỗng thì bỏ dòng), reask: list chuỗi "hàng — giá lần
    trước" cho mặt hàng NCC vừa báo gần đây (đã điền sẵn, chỉ cần xác nhận); rỗng thì bỏ.
    Trả: chuỗi nhiều dòng. Nhiều báo giá thì liệt kê các số, cách nhau dấu phẩy.
    """
    subject = f"yêu cầu báo giá {', '.join(quote_names)}"
    first = f"{company_name} gửi {subject}"
    lines = [
        f"Kính gửi {vendor_name},",
        first + (f", hạn {deadline_text}." if deadline_text else "."),
        f"Link báo giá: {url}",
    ]
    if password:
        lines.append(f"Mật khẩu: {password}")
    if requester:
        lines.append(f"Người hỏi giá: {requester}")
    if reask:
        lines.append("Hàng quý công ty vừa báo giá gần đây (giá cũ đã điền sẵn, nhờ xác nhận còn hàng / đúng giá):")
        lines += [f"- {item}" for item in reask]
    return "\n".join(lines)


def deadline_hint(deadline, today, urgent_days=2):
    """Nhắc hạn báo giá cho NCC.

    Nhận: ngày hạn (date hoặc None), hôm nay (date), số ngày coi là gấp.
    Trả: (chữ, mức) với mức "over" (đã quá hạn), "urgent" (hôm nay hoặc còn <= urgent_days
    ngày), "ok" (còn xa). Không có hạn → ("", "").
    """
    if not deadline:
        return "", ""
    days = (deadline - today).days
    if days < 0:
        return "Đã quá hạn", "over"
    if days == 0:
        return "Hết hạn hôm nay", "urgent"
    return f"Còn {days} ngày", "urgent" if days <= urgent_days else "ok"


ATTACHMENT_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "webp", "heic",
    "pdf", "xls", "xlsx", "csv", "doc", "docx", "txt", "zip",
}
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}


def file_extension(filename):
    """Đuôi tệp viết thường, không dấu chấm: "Bao gia.PDF" → "pdf". Không có đuôi → ""."""
    name = (filename or "").strip()
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def attachment_error(filename, size, max_bytes):
    """Lý do không nhận một tệp đính kèm tin trao đổi, hoặc "" nếu nhận được.

    Nhận: tên tệp, kích thước (byte), giới hạn (byte). Chỉ nhận ảnh / PDF / Excel / Word /
    CSV / TXT / ZIP — tệp chạy được (exe, js, html…) bị từ chối vì người tải về là nhân viên.
    """
    if not (filename or "").strip():
        return "Tệp không có tên."
    if file_extension(filename) not in ATTACHMENT_EXTENSIONS:
        return f"Không nhận loại tệp \"{filename}\" — chỉ ảnh, PDF, Excel, Word, CSV, TXT, ZIP."
    if size > max_bytes:
        return f"Tệp \"{filename}\" quá {max_bytes // (1024 * 1024)}MB."
    if size <= 0:
        return f"Tệp \"{filename}\" rỗng."
    return ""


def normalize_origin(text):
    """Chuẩn hoá "Tài liệu gốc" (mã đơn hàng của khách) sale gõ cho đơn mua.

    Nhận chuỗi tự do: một hoặc nhiều mã, cách nhau dấu phẩy, chấm phẩy hoặc xuống dòng.
    Trả các mã đã gọn khoảng trắng, bỏ trùng (giữ thứ tự), nối bằng ", " — đồng bộ MISA tách
    origin theo dấu phẩy rồi strip từng mã. Rỗng / None / toàn dấu phân cách → "".
    """
    codes = []
    for part in re.split(r"[,;\n]+", text or ""):
        code = " ".join(part.split())
        if code and code not in codes:
            codes.append(code)
    return ", ".join(codes)


DEFAULT_PRICE_VALID_DAYS = 7
CLOSE_GRACE_DAYS = 7


def default_price_valid_until(submit_day, days=DEFAULT_PRICE_VALID_DAYS):
    """Hạn giá mặc định khi NCC không ghi: ngày gửi giá + days. submit_day: date; None → None."""
    return submit_day + timedelta(days=days) if submit_day else None


def inquiry_close_day(price_valid_untils, deadline, created_day, grace_days=CLOSE_GRACE_DAYS):
    """Ngày cuối phiếu chưa lên YCMH còn mở; qua ngày này thì tự đóng "Không mua".

    price_valid_untils: list date hiệu lực giá của các NCC đã báo (bỏ None). Có → ngày muộn
    nhất (còn NCC nào giữ giá thì còn mở). Chưa NCC nào báo → (hạn báo giá, không có thì ngày
    tạo) + grace_days. Thiếu cả hạn lẫn ngày tạo → None (không tự đóng).
    """
    valid = [day for day in price_valid_untils if day]
    if valid:
        return max(valid)
    base = deadline or created_day
    return base + timedelta(days=grace_days) if base else None


def summarize_vendor_prices(purchases, quotes):
    """Tóm tắt giá theo từng NCC cho trang tra giá.

    purchases / quotes: list dict đã sắp mới nhất trước, mỗi dict có vendor_id, vendor,
    day (chuỗi yyyy-mm-dd để so), price (đơn giá đem so). Trả list dict {vendor_id, vendor,
    last_purchase, min_purchase, purchase_count, last_quote, min_quote, quote_count, last_day}
    — last_* / min_* là chính dict dòng (None nếu NCC chưa có loại đó), sắp theo hoạt động gần
    nhất trước. Dòng quote có "unavailable" thật thì không tính vào min_quote. Rỗng → [].
    """
    summary = {}

    def entry(row):
        return summary.setdefault(row["vendor_id"], {
            "vendor_id": row["vendor_id"], "vendor": row["vendor"],
            "last_purchase": None, "min_purchase": None, "purchase_count": 0,
            "last_quote": None, "min_quote": None, "quote_count": 0, "last_day": "",
        })

    for kind, rows in (("purchase", purchases), ("quote", quotes)):
        for row in rows:
            item = entry(row)
            item[kind + "_count"] += 1
            if item["last_" + kind] is None:
                item["last_" + kind] = row
            if not row.get("unavailable") and row["price"] > 0:
                current = item["min_" + kind]
                if current is None or row["price"] < current["price"]:
                    item["min_" + kind] = row
            item["last_day"] = max(item["last_day"], row["day"] or "")
    return sorted(summary.values(), key=lambda item: item["last_day"], reverse=True)
