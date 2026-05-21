#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grep_sync_log.py
=================
Đọc log Odoo để xác định đơn hàng đã đi qua code path nào khi sync MISA.
Hỗ trợ file .gz (Odoo.sh log rotation).

Cách chạy:
  1. Standalone (Odoo.sh):
       python bin/grep_sync_log.py ~/logs/odoo.log.2026-05-04.gz

  2. Lọc theo thời gian (VN UTC+7 → script tự trừ 7h để ra UTC):
       TIME_VN=08:29 python bin/grep_sync_log.py ~/logs/odoo.log.2026-05-04.gz
       TIME_WIN=30  # ±30 phút (mặc định)

  3. Trong Odoo shell (IPython):
       import os; os.environ['TIME_VN']='08:29'
       exec(open('bin/grep_sync_log.py').read())

  4. Qua odoo-bin shell:
       python odoo-bin shell -d <DB> < bin/grep_sync_log.py
"""

import os
import sys
import re
import gzip
import glob
from datetime import datetime, timedelta

# ─── Cấu hình ────────────────────────────────────────────────────────────────
ORDER    = os.environ.get("ORDER", "DH125524949231179")
TAIL     = int(os.environ.get("TAIL", "0"))        # 0 = đọc toàn bộ file
CTX      = int(os.environ.get("CTX", "5"))          # dòng context trước/sau

# Lọc theo giờ VN (UTC+7): ví dụ TIME_VN=08:29
# Script tự convert sang UTC và lọc ±TIME_WIN phút
TIME_VN  = os.environ.get("TIME_VN", "")           # "HH:MM" giờ Việt Nam
TIME_WIN = int(os.environ.get("TIME_WIN", "30"))    # ±phút

# Log file: ưu tiên argument, rồi env, rồi tự tìm
# Tự glob *.gz files trong ~/logs/ và sắp xếp mới nhất lên trên
_gz_files = sorted(
    glob.glob(os.path.expanduser("~/logs/odoo.log.*.gz")),
    reverse=True   # mới nhất trước
)
LOG_CANDIDATES = [
    os.path.expanduser("~/logs/odoo.log"),          # Odoo.sh plain
    os.path.expanduser("~/logs/odoo.log.1"),
    *_gz_files,                                     # ~/logs/odoo.log.2026-05-04.gz ...
    "/var/log/odoo/odoo-server.log",
    "/var/log/odoo/odoo.log",
    "/opt/odoo/logs/odoo-server.log",
    "/home/odoo/logs/odoo-server.log",
]

SEP  = "=" * 72
SEP2 = "-" * 72

def p(s=""): print(s)
def section(title): p(f"\n{SEP}\n  {title}\n{SEP}")
def sub(title):     p(f"\n  {SEP2}\n  {title}\n  {SEP2}")

# ─── Tìm log file ─────────────────────────────────────────────────────────────
log_path = None

if len(sys.argv) > 1:
    log_path = sys.argv[1]
else:
    log_path = os.environ.get("LOG")
    if not log_path:
        for c in LOG_CANDIDATES:
            if os.path.exists(c):
                log_path = c
                break

if not log_path or not os.path.exists(log_path):
    p("⚠️  Không tìm thấy log file tự động. Thử tìm trong hệ thống...")
    import subprocess
    try:
        # Tìm trong ~/logs/ trước, bỏ qua backup
        result = subprocess.run(
            ["find",
             os.path.expanduser("~/logs"),
             "/var/log/odoo", "/opt/odoo/logs",
             "-name", "odoo*.log", "-o", "-name", "odoo*.log.gz"],
            capture_output=True, text=True, timeout=5
        )
        found = [
            l for l in result.stdout.splitlines()
            if "odoo" in l.lower() and "backup" not in l
        ]
        # Ưu tiên .gz có ngày tháng
        found.sort(key=lambda x: ("odoo.log." not in x, x), reverse=False)
        found.sort(key=lambda x: x.endswith(".gz"), reverse=True)
        if found:
            p("   Tìm thấy:")
            for f in found[:8]: p(f"     {f}")
            log_path = found[0]
            p(f"   → Dùng: {log_path}")
        else:
            p("❌ Không tìm thấy. Chỉ định: python bin/grep_sync_log.py ~/logs/odoo.log.2026-05-04.gz")
            sys.exit(1)
    except Exception:
        p("❌ Không thể tìm log. Chỉ định: python bin/grep_sync_log.py ~/logs/odoo.log.2026-05-04.gz")
        sys.exit(1)

# ─── Tính time range UTC từ TIME_VN ──────────────────────────────────────────
time_filter_start = None
time_filter_end   = None
if TIME_VN:
    try:
        # Lấy ngày từ tên file log nếu có (vd: odoo.log.2026-05-04.gz)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", log_path)
        if date_match:
            log_date = date_match.group(1)
        else:
            log_date = datetime.utcnow().strftime("%Y-%m-%d")

        vn_dt = datetime.strptime(f"{log_date} {TIME_VN}", "%Y-%m-%d %H:%M")
        utc_dt = vn_dt - timedelta(hours=7)   # VN = UTC+7
        time_filter_start = utc_dt - timedelta(minutes=TIME_WIN)
        time_filter_end   = utc_dt + timedelta(minutes=TIME_WIN)
        p(f"  Lọc VN {TIME_VN} (±{TIME_WIN} phút) → UTC [{time_filter_start.strftime('%H:%M')} – {time_filter_end.strftime('%H:%M')}]")
    except Exception as e:
        p(f"  ⚠️  Lỗi parse TIME_VN='{TIME_VN}': {e}. Bỏ qua lọc thời gian.")

p(SEP)
p(f"  ODOO MISA SYNC PATH CHECKER")
p(f"  Order    : {ORDER}")
p(f"  Log file : {log_path}")
p(f"  Tail     : {TAIL:,} dòng cuối")
p(SEP)

# ─── Đọc file (hỗ trợ .gz) ───────────────────────────────────────────────────
try:
    if log_path.endswith(".gz"):
        with gzip.open(log_path, "rt", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    else:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

    if TAIL > 0:
        lines = all_lines[-TAIL:]
    else:
        lines = all_lines

    # Lọc theo time range nếu có TIME_VN
    if time_filter_start and time_filter_end:
        ts_rx = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
        filtered = []
        current_ts = None
        for line in lines:
            m = ts_rx.match(line)
            if m:
                try:
                    current_ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            if current_ts and time_filter_start <= current_ts <= time_filter_end:
                filtered.append(line)
        p(f"  → Đọc {len(lines):,} / {len(all_lines):,} dòng tổng; sau lọc giờ: {len(filtered):,} dòng")
        lines = filtered
    else:
        p(f"  → Đọc {len(lines):,} / {len(all_lines):,} dòng tổng cộng")

except Exception as e:
    p(f"❌ Không đọc được file: {e}")
    sys.exit(1)

# ─── Hàm grep helper ──────────────────────────────────────────────────────────
def grep(pattern, data=None, flags=re.IGNORECASE, limit=None):
    data = data or lines
    rx = re.compile(pattern, flags)
    results = [(i+1, l.rstrip()) for i, l in enumerate(data) if rx.search(l)]
    if limit:
        results = results[-limit:]
    return results

def show(matches, indent="  "):
    if not matches:
        p(f"{indent}(không có kết quả)")
    for lineno, text in matches:
        p(f"{indent}{lineno:6d}: {text}")

def grep_context(pattern, data=None, ctx=CTX, limit=150):
    """Trả về các dòng trong context xung quanh match"""
    data = data or lines
    rx = re.compile(pattern, re.IGNORECASE)
    matched_indices = [i for i, l in enumerate(data) if rx.search(l)]
    seen = set()
    out = []
    for idx in matched_indices:
        for j in range(max(0, idx - ctx), min(len(data), idx + ctx + 1)):
            if j not in seen:
                seen.add(j)
                out.append((j+1, data[j].rstrip()))
    # Sắp xếp và giới hạn
    out.sort(key=lambda x: x[0])
    return out[-limit:]

# ═════════════════════════════════════════════════════════════════════════════
section(f"[1] XÁC ĐỊNH CODE PATH (full resync vs partial resync)")

sub("Full resync (xoá & tạo lại)")
show(grep(r"(thành công|thanh cong).{0,30}" + re.escape(ORDER) +
          r"|" + re.escape(ORDER) + r".{0,50}(thành công|xoá|tạo lại)", limit=10))

sub("Partial resync (có picking done)")
show(grep(r"partial resync|B.t đ.u partial resync.*" + re.escape(ORDER) +
          r"|=== B.t đ.u partial", limit=10))

# ═════════════════════════════════════════════════════════════════════════════
section(f"[2] TẤT CẢ DÒNG LOG LIÊN QUAN ĐẾN ĐƠN {ORDER}")
show(grep(re.escape(ORDER), limit=80))

# ═════════════════════════════════════════════════════════════════════════════
section("[3] CÁC BƯỚC TRONG _partial_resync (nếu có chạy)")

sub("Step 2: MISA Total (sản phẩm nào được tính / skip)")
show(grep(r"MISA Total|Step2.*skip|skip child.*BoM|skip.*child.*parent", limit=30))

sub("Step 3: Need in open / Over-delivery")
show(grep(r"Need in open|Over-delivery|CHẶN ĐỒNG BỘ|needed_in_open", limit=30))

sub("Step 4: Trigger procurement")
show(grep(r"trigger.*procurement|Triggered stock rule|Còn sản phẩm cần giao|_action_launch|nothing_to_ship", limit=20))

# ═════════════════════════════════════════════════════════════════════════════
section("[4] CÁC SẢN PHẨM COMBO LIÊN QUAN")
show(grep(r"M18.*FPD|M18B5|M12-18C|M18FUEL|M18FUELCHARGER|bom_line|has_kits|BoM Kit|phantom|combo", limit=40))

# ═════════════════════════════════════════════════════════════════════════════
section("[5] LỖI / CẢNH BÁO")

# Tìm timestamp gần nhất của đơn
order_matches = grep(re.escape(ORDER))
if order_matches:
    last_lineno, last_line = order_matches[-1]
    # Tìm timestamp dạng "2025-05-20 14:30:00" trong vùng log xung quanh
    ts_match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", last_line)
    if ts_match:
        ts = ts_match.group()
        p(f"  → Xung quanh thời điểm: {ts}")
        # Lấy vùng ±200 dòng xung quanh lần xuất hiện cuối
        start = max(0, last_lineno - 200)
        end   = min(len(lines), last_lineno + 50)
        window = lines[start:end]
        err_matches = grep(r"ERROR|WARNING|CRITICAL", data=window, limit=30)
        show(err_matches)
    else:
        show(grep(r"ERROR|WARNING", limit=20))
else:
    p(f"  (không tìm thấy '{ORDER}' trong log)")
    show(grep(r"ERROR|WARNING", limit=20))

# ═════════════════════════════════════════════════════════════════════════════
section(f"[6] CONTEXT ĐẦY ĐỦ (±{CTX} dòng) XUNG QUANH '{ORDER}'")
ctx_matches = grep_context(re.escape(ORDER))
if ctx_matches:
    prev_lineno = None
    for lineno, text in ctx_matches:
        if prev_lineno and lineno - prev_lineno > 1:
            p("  ...")
        marker = ">>>" if ORDER in text else "   "
        p(f"  {marker} {lineno:6d}: {text}")
        prev_lineno = lineno
else:
    p(f"  (không tìm thấy '{ORDER}')")

p()
p(SEP)
p(f"  XONG. Tìm '{ORDER}' trong {len(lines):,} dòng cuối của {log_path}")
p(SEP)
