# Truy vì sao một mã hàng CÓ trên Odoo mà KHÔNG có trên MISA CRM: ai tạo, lúc nào, lúc đó MISA
# trả gì (đọc log server Odoo.sh), và bây giờ MISA đang có gì theo mã / theo MISA ID.
#
# CHỈ ĐỌC — không ghi gì (chỉ gọi các API tra cứu của MISA).
# CÁCH CHẠY: sửa CẤU HÌNH, copy TOÀN BỘ file dán vào notebook Odoo-shell (cùng nhánh với nơi
# xảy ra chuyện: log server là của container đó), copy kết quả gửi lại.
#
# Đường tạo hàng thường (misa.api.utils._create_product_misa_raw) chỉ tạo sản phẩm Odoo SAU khi
# MISA trả Success kèm ID, và ghi log:
#     📤 [MISA RAW REQUEST] Code: <mã>
#     MISA CRM cổng g1 lỗi máy chủ (Product, HTTP 502): ...      <- nếu một cổng lỗi rồi đổi cổng
#     📥 [MISA RESPONSE] Status: <http> | Body: <nguyên văn MISA trả>
#     Đã tạo / Đã cập nhật sản phẩm Odoo: ...
# Nên nếu sản phẩm Odoo ra đời từ đường này thì MISA ĐÃ báo thành công — xem Body và ID ở mục D,
# rồi mục C cho biết ID đó bây giờ còn trên MISA không (bị xoá / đổi mã sau đó).
exec(r'''
# ── CẤU HÌNH ─────────────────────────────────────────────────────────────────
CODES = ("ABC123",)     # <-- mã hàng Odoo cần truy (default_code)
WINDOW_MIN = 10         # mục D: lấy log quanh giờ tạo sản phẩm Odoo ± ngần này phút
TRACE_LINES = 40        # số dòng traceback in kèm sau một dòng log khớp
MAX_LINE = 1500         # cắt dòng log dài (Body MISA có thể rất dài)
# ─────────────────────────────────────────────────────────────────────────────

import glob
import gzip
import os
import re
from datetime import datetime, timedelta

import pytz

TZ = pytz.timezone("Asia/Ho_Chi_Minh")
SEP = "=" * 90
LOG_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ ")
# Các logger liên quan tới tạo / sửa hàng MISA — dòng khớp trong khung giờ đều in ra, kể cả
# dòng không chứa mã (VD "cổng g1 lỗi máy chủ" không ghi mã hàng).
MISA_LINE = re.compile(
    r"MISA RAW REQUEST|MISA RESPONSE|MISA CRM cổng|MISA_PRODUCT_API|MISA_PRODUCT_SYNC|PRODUCT_AGENT"
    r"|sản phẩm Odoo|Lỗi API Create|MISA Refused|Token CRM|misa_api_utils|misa_crm_gateway"
)

misa = env["misa.api.utils"].sudo()
Template = env["product.template"].sudo().with_context(active_test=False)


def local(dt):
    return pytz.utc.localize(dt).astimezone(TZ).strftime("%d/%m/%Y %H:%M:%S") if dt else "-"


def section(title):
    print("\n%s\n  %s\n%s" % (SEP, title, SEP))


def cut(text, limit=MAX_LINE):
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + " …(+%s ký tự)" % (len(text) - limit)


def misa_by_code(code):
    try:
        return misa._find_exact_crm_product_by_code(code), None
    except Exception as error:
        return None, error


def misa_by_id(misa_id):
    """Đọc thẳng form hàng trên MISA theo ID, trả (http, Success, mã, tên, body rút gọn)."""
    try:
        res, data = misa._crm_post("Product/FormDataNew/Product/45/4", {"ID": str(misa_id)},
                                   misa._crm_product_headers())
    except Exception as error:
        return "lỗi mạng: %s" % error
    data = data or {}
    raw = data.get("Data") or {}
    current = (raw.get("CurrentData") or raw) if isinstance(raw, dict) else {}
    return "HTTP %s Success=%s mã=%s tên=%s | %s" % (
        res.status_code, data.get("Success"), current.get("ProductCode"),
        current.get("ProductName"), cut(res.text, 300))


def log_files(days):
    """File log Odoo.sh có thể chứa các ngày (UTC) này: file đang ghi + bản nén theo ngày."""
    paths = []
    for path in glob.glob(os.path.expanduser("~/logs/odoo.log*")):
        name = os.path.basename(path)
        if name in ("odoo.log", "odoo.log.1") or any(d.strftime("%Y-%m-%d") in name for d in days):
            paths.append(path)
    return sorted(paths)


def scan_log(path, code, t_from, t_to):
    """In dòng chứa mã (cả file) và dòng MISA trong khung giờ, kèm traceback theo sau."""
    opener = gzip.open if path.endswith(".gz") else open
    hits = tail = 0
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            m = LOG_TS.match(line)
            if not m:
                if tail:  # dòng nối (traceback) của một dòng vừa khớp
                    print("        " + cut(line, 300))
                    tail -= 1
                continue
            tail = 0
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            in_window = t_from <= ts <= t_to
            if code in line or (in_window and MISA_LINE.search(line)):
                print("  [%s VN] %s" % (local(ts)[-8:], cut(line[24:])))
                hits += 1
                tail = TRACE_LINES
    return hits


def check(code):
    section("MÃ %s" % code)

    # ── A. Sản phẩm Odoo ──────────────────────────────────────────────────────
    products = Template.search([("default_code", "=", code)])
    if not products:
        print("  A. Không có product.template nào default_code = %s (thử tìm gần đúng):" % code)
        for p in Template.search([("default_code", "ilike", code)], limit=10):
            print("     %s  %s" % (p.default_code, p.name))
        return
    product = products[0]
    print("  A. Odoo: id=%s  '%s'  active=%s  misa_product_id=%s" % (
        product.id, product.name, product.active, product.misa_product_id or "-"))
    print("     tạo %s bởi %s  ·  sửa cuối %s bởi %s" % (
        local(product.create_date), product.create_uid.login,
        local(product.write_date), product.write_uid.login))
    if len(products) > 1:
        print("     !! %s sản phẩm cùng mã: %s" % (len(products), products.ids))
    msgs = env["mail.message"].sudo().search(
        [("model", "=", "product.template"), ("res_id", "=", product.id)], order="date asc")
    for msg in msgs:
        body = " ".join((msg.body or "").striptags().split()) if msg.body else ""
        tracks = "; ".join("%s: %s → %s" % (
            tv.field_id.name, tv.old_value_char or "", tv.new_value_char or "") for tv in msg.tracking_value_ids)
        if body or tracks:
            print("     chatter %s %s: %s %s" % (local(msg.date), msg.author_id.name or "-",
                                                cut(body, 200), tracks))

    # ── B. Dấu vết trong DB: trợ lý tạo hàng, lịch sử đổi mã ─────────────────
    misa_ids = {product.misa_product_id} - {False, ""}
    if "hlv.product.agent.log" in env:
        for lg in env["hlv.product.agent.log"].sudo().search(
                [("product_code", "=", code)], order="create_date asc"):
            misa_ids.add(lg.misa_id)
            print("  B. trợ lý %s  %-7s %s (%s)  MISA ID=%s  phiên=%s  sửa %s: %s → %s" % (
                local(lg.create_date), lg.action, lg.sale_name or "-", lg.user_id.login,
                lg.misa_id or "-", lg.session_id.id or "-", lg.updated_field or "-",
                lg.old_value or "", lg.new_value or ""))
    History = env["misa.product.code.history"].sudo()
    for h in History.search(["|", ("old_code", "=", code), ("new_code", "=", code)], order="create_date asc"):
        misa_ids.add(h.misa_id)
        print("  B. đổi mã %s  %s → %s  MISA ID=%s  nguồn=%s %s  MISA=%s Odoo=%s  %s" % (
            local(h.create_date), h.old_code, h.new_code, h.misa_id or "-", h.source,
            h.actor or h.user_id.login or "", h.misa_updated, h.odoo_updated, h.note or ""))
    misa_ids.discard(False)
    misa_ids.discard("")

    # ── C. MISA bây giờ ──────────────────────────────────────────────────────
    found, error = misa_by_code(code)
    if error:
        print("  C. Tra mã trên MISA LỖI: %s" % error)
    elif found:
        print("  C. MISA ĐANG CÓ mã này: %s" % found)
    else:
        print("  C. MISA không có mã %s (tra đúng mã)." % code)
    for misa_id in sorted(misa_ids):
        print("  C. MISA ID %s: %s" % (misa_id, misa_by_id(misa_id)))

    # ── D. Log server quanh lúc tạo ──────────────────────────────────────────
    t_from = product.create_date - timedelta(minutes=WINDOW_MIN)
    t_to = product.create_date + timedelta(minutes=WINDOW_MIN)
    days = {(product.create_date + timedelta(days=k)).date() for k in (-1, 0, 1)}
    files = log_files(days)
    print("  D. Log server: dòng chứa '%s' + dòng MISA trong %s → %s (VN)" % (
        code, local(t_from), local(t_to)))
    if not files:
        print("     Không còn file log cho ngày %s trong ~/logs (Odoo.sh chỉ giữ vài ngày)." %
              product.create_date.date())
    for path in files:
        print("   --- %s" % path)
        if not scan_log(path, code, t_from, t_to):
            print("     (không có dòng nào)")


print("DB: %s · lúc %s · log: %s" % (env.cr.dbname, local(datetime.utcnow()),
                                     ", ".join(sorted(glob.glob(os.path.expanduser("~/logs/odoo.log*"))))))
for c in CODES:
    check(c)
''')
