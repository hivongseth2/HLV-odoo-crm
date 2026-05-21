# grep_sync_log.sh
# ==================
# Đọc log Odoo để xác định đơn hàng đã đi qua code path nào khi sync MISA
# Chạy TRÊN MÁY CHỦ Odoo (Linux):
#
#   chmod +x bin/grep_sync_log.sh
#   bash bin/grep_sync_log.sh
#
# Tuỳ chỉnh:
#   ORDER=DH125524949231179 LOG=/path/to/odoo.log bash bin/grep_sync_log.sh
#   TAIL=5000 bash bin/grep_sync_log.sh      # chỉ đọc 5000 dòng cuối

LOG="${LOG:-/var/log/odoo/odoo-server.log}"
ORDER="${ORDER:-DH125524949231179}"
TAIL="${TAIL:-100}"   # đọc N dòng cuối log (tránh file quá lớn)
CTX="${CTX:-3}"         # số dòng context trước/sau mỗi match

SEP="========================================================================"
SEP2="------------------------------------------------------------------------"

echo "$SEP"
echo "  ODOO MISA SYNC PATH CHECKER"
echo "  Order    : $ORDER"
echo "  Log file : $LOG"
echo "  Tail     : $TAIL dòng cuối"
echo "$SEP"

# ─── Tìm log file nếu không tồn tại ────────────────────────────────────────
if [ ! -f "$LOG" ]; then
    echo "⚠️  File không tồn tại: $LOG  → tìm tự động..."
    FOUND=$(find /var/log /home /opt /root -name "*.log" 2>/dev/null | grep -i odoo | head -5)
    if [ -z "$FOUND" ]; then
        echo "❌ Không tìm thấy log Odoo. Chỉ định bằng: LOG=/path/to/file bash $0"
        exit 1
    fi
    echo "   Tìm thấy:"
    echo "$FOUND"
    LOG=$(echo "$FOUND" | head -1)
    echo "   → Dùng: $LOG"
fi

# Dùng tail để tránh đọc file quá lớn
LOGDATA=$(tail -n "$TAIL" "$LOG")

echo ""
echo "$SEP"
echo "  [1] XÁC ĐỊNH CODE PATH (full resync vs partial resync)"
echo "$SEP"

echo ""
echo "--- Full resync (xoá & tạo lại) ---"
echo "$LOGDATA" | grep -n "xo.*t.o l.i th.*nh c.ng.*$ORDER\|$ORDER.*xo.*t.o l.i\|Đồng bộ.*thành công.*$ORDER\|thành công.*$ORDER" | tail -20

echo ""
echo "--- Partial resync (có picking done) ---"
echo "$LOGDATA" | grep -n "partial resync.*$ORDER\|$ORDER.*partial\|B.t đ.u partial resync" | grep -i "$ORDER\|partial resync" | tail -20

echo ""
echo "$SEP"
echo "  [2] TẤT CẢ DÒNG LOG LIÊN QUAN ĐẾN ĐƠN $ORDER"
echo "$SEP"
echo "$LOGDATA" | grep -n "$ORDER" | tail -80

echo ""
echo "$SEP"
echo "  [3] CÁC BƯỚC TRONG _partial_resync (nếu có chạy)"
echo "$SEP"

echo ""
echo "--- Step 2: MISA Total (sản phẩm nào được tính) ---"
echo "$LOGDATA" | grep -n "MISA Total\|Step2.*skip child\|skip child.*BoM" | tail -30

echo ""
echo "--- Step 3: Need in open / Over-delivery ---"
echo "$LOGDATA" | grep -n "Need in open\|Over-delivery\|CHẶN ĐỒNG BỘ\|needed_in_open" | tail -30

echo ""
echo "--- Step 4: Trigger procurement ---"
echo "$LOGDATA" | grep -n "trigger.*procurement\|Triggered stock rule\|nothing_to_ship\|_action_launch\|Còn sản phẩm" | tail -20

echo ""
echo "$SEP"
echo "  [4] CÁC SẢN PHẨM COMBO LIÊN QUAN (M18, M12-18)"
echo "$SEP"
echo "$LOGDATA" | grep -n "M18.*FPD\|M18B5\|M12-18C\|M18FUEL\|combo.*$ORDER\|$ORDER.*combo\|bom_line\|has_kits\|BoM Kit\|phantom" | tail -40

echo ""
echo "$SEP"
echo "  [5] LỖI / CẢNH BÁO TRONG KHU VỰC SYNC ĐƠN NÀY"
echo "$SEP"

# Lấy timestamp của lần sync gần nhất đơn này, rồi tìm ERROR/WARNING trong khoảng 60s
LAST_TS=$(echo "$LOGDATA" | grep "$ORDER" | tail -1 | grep -oP '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}' | head -1)
if [ -n "$LAST_TS" ]; then
    echo "  → Xung quanh thời điểm: $LAST_TS"
    echo "$LOGDATA" | awk -v ts="$LAST_TS" '
        /^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}/ { current_ts = $1" "$2 }
        current_ts >= ts && /ERROR|WARNING|CRITICAL/ { print NR": "current_ts" "$0 }
    ' | head -30
else
    echo "$LOGDATA" | grep -n "ERROR\|WARNING" | grep -i "sale\|picking\|misa\|sync\|combo\|bom" | tail -20
fi

echo ""
echo "$SEP"
echo "  [6] CONTEXT ĐẦY ĐỦ XUNG QUANH CÁC DÒNG CÓ $ORDER"
echo "      (dùng để trace luồng chính xác)"
echo "$SEP"
echo "$LOGDATA" | grep -n -B "$CTX" -A "$CTX" "$ORDER" | tail -150

echo ""
echo "$SEP"
echo "  XONG. Tìm kiếm: '$ORDER' trong $TAIL dòng cuối của $LOG"
echo "$SEP"
