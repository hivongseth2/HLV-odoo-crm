# Đọc log server Odoo.sh xem API mã hàng (/api/misa/product|combo/...) trả gì, KHÔNG cần biết mã.
# Dùng khi bên gọi báo "API tạo mã MISA trả 502" mà không rõ lỗi ở đâu.
#
# CHỈ ĐỌC. CÁCH CHẠY (cùng nhánh bên gọi đã gọi tới — thường là prd):
#     python3 bin/grep_misa_product_api_log.py          (tab SHELL, file đã có trên container)
# hoặc dán cả file vào notebook Odoo-shell. Copy kết quả gửi lại.
#
# Đọc kết quả:
#   - Dòng werkzeug "POST /api/misa/product/create ... 502" có thời gian xử lý (cột cuối) gần 0 và
#     KHÔNG có dòng MISA RAW REQUEST theo sau → lỗi trong Odoo trước khi gọi MISA: traceback nằm
#     ở dòng "MISA_PRODUCT_API create_product lỗi" ngay trên.
#   - Có "MISA RAW REQUEST" + "MISA CRM cổng ... HTTP 502" → MISA thật sự lỗi máy chủ.
#   - Không có dòng werkzeug nào cho /api/misa/ → request không tới được Odoo (proxy Odoo.sh
#     trả 502, hoặc gọi nhầm nhánh / domain).
import glob
import gzip
import os
import re
from datetime import datetime, timedelta

# ── CẤU HÌNH ─────────────────────────────────────────────────────────────────
DAYS = 2                # đọc log của ngần này ngày gần nhất (theo ngày UTC trong tên file)
TIME_VN_FROM = ""       # "03/11 14:00" để chỉ lấy từ giờ VN này; rỗng = cả DAYS
TIME_VN_TO = ""         # "03/11 15:00"; rỗng = tới cuối log
TRACE_LINES = 60        # số dòng traceback in kèm sau một dòng khớp
MAX_LINE = 1500         # cắt dòng log dài (Body MISA có thể rất dài)
# ─────────────────────────────────────────────────────────────────────────────

VN = timedelta(hours=7)
LOG_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ ")
API_HIT = re.compile(r'"(?:POST|GET) (/api/misa/(?:product|combo)/\w+) [^"]*" (\d{3})')
# Logger của API mã hàng và các bước gọi MISA phía sau nó.
MISA_LINE = re.compile(
    r"MISA_PRODUCT_API|MISA RAW REQUEST|MISA RESPONSE|MISA CRM cổng|MISA Refused|Token CRM"
    r"|Lỗi API Create|tạo combo|sản phẩm Odoo|/api/misa/(?:product|combo)/"
)
# Route search được gọi hàng trăm lần và log "MISA RESPONSE Staus" (sai chính tả, chỉ ở
# search) cả body — in ra là tràn màn hình. Chỉ đếm, không in, trừ khi search trả khác 200.
NOISE = re.compile(r"MISA RESPONSE\] Staus:")
QUIET_ROUTES = {"/api/misa/product/search"}


def parse_vn(text):
    """'03/11 14:00' giờ VN -> datetime UTC (năm hiện tại). Rỗng -> None."""
    if not text.strip():
        return None
    return datetime.strptime("%s/%s" % (text.strip(), datetime.utcnow().year), "%d/%m %H:%M/%Y") - VN


def cut(text, limit=MAX_LINE):
    return text if len(text) <= limit else text[:limit] + " …(+%s ký tự)" % (len(text) - limit)


def log_files(days):
    """File đang ghi + bản nén của DAYS ngày gần nhất, cũ trước mới sau."""
    today = datetime.utcnow().date()
    wanted = {(today - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(days + 1)}
    paths = []
    for path in glob.glob(os.path.expanduser("~/logs/odoo.log*")):
        name = os.path.basename(path)
        if name in ("odoo.log", "odoo.log.1") or any(d in name for d in wanted):
            paths.append(path)
    # odoo.log là file đang ghi (mới nhất) nên xếp cuối.
    return sorted(paths, key=lambda p: (os.path.basename(p) == "odoo.log", p))


def scan(path, t_from, t_to, stats):
    opener = gzip.open if path.endswith(".gz") else open
    hits = tail = 0
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            m = LOG_TS.match(line)
            if not m:
                if tail:  # dòng nối (traceback) của dòng vừa khớp
                    print("        " + cut(line, 300))
                    tail -= 1
                continue
            tail = 0
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            if (t_from and ts < t_from) or (t_to and ts > t_to) or not MISA_LINE.search(line):
                continue
            if NOISE.search(line):
                continue
            hit = API_HIT.search(line)
            if hit:
                key = "%s %s" % (hit.group(1), hit.group(2))
                stats[key] = stats.get(key, 0) + 1
                if hit.group(1) in QUIET_ROUTES and hit.group(2) == "200":
                    continue
            print("  [%s VN] %s" % ((ts + VN).strftime("%d/%m %H:%M:%S"), cut(line[24:])))
            hits += 1
            tail = TRACE_LINES
    return hits


def run():
    t_from, t_to = parse_vn(TIME_VN_FROM), parse_vn(TIME_VN_TO)
    files = log_files(DAYS)
    print("Log có trong ~/logs: %s" % ", ".join(sorted(glob.glob(os.path.expanduser("~/logs/odoo.log*")))))
    if not files:
        print("Không có file log nào cho %s ngày gần nhất." % DAYS)
        return
    stats = {}
    for path in files:
        print("\n" + "=" * 90 + "\n  " + path + "\n" + "=" * 90)
        if not scan(path, t_from, t_to, stats):
            print("  (không có dòng nào)")
    print("\nTỔNG request /api/misa/product|combo theo route + mã HTTP:")
    for key in sorted(stats):
        print("  %-40s %s" % (key, stats[key]))
    if not stats:
        print("  không có request nào tới Odoo")


run()
