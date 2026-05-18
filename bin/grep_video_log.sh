#!/bin/bash
# grep_video_log.sh
# ==================
# Lọc log server Odoo để tìm nguyên nhân video không upload được
# Chạy TRÊN MÁY CHỦ Odoo (Linux):
#
#   chmod +x bin/grep_video_log.sh
#   bash bin/grep_video_log.sh
#
# Hoặc chỉ định file log:
#   LOG=/path/to/odoo.log bash bin/grep_video_log.sh

LOG="${LOG:-/var/log/odoo/odoo-server.log}"
LINES="${LINES:-200}"
ORDER="${ORDER:-DH125524949231713}"

SEP="========================================================================"

echo "$SEP"
echo "  ODOO VIDEO UPLOAD LOG CHECKER"
echo "  Log file : $LOG"
echo "  Max lines: $LINES"
echo "$SEP"

if [ ! -f "$LOG" ]; then
    echo "❌ File log không tồn tại: $LOG"
    echo "   Thử tìm log Odoo..."
    find /var/log /home /opt -name "*.log" 2>/dev/null | grep -i odoo | head -10
    exit 1
fi

echo ""
echo "──── 1. LỖI BG_UPLOAD (fatal / refresh / authorize) ────"
grep -n "BG_UPLOAD" "$LOG" | grep -iE "fatal|error|exception|fail|missing|refresh|authorize|token" | tail -$LINES

echo ""
echo "──── 2. TẤT CẢ BG_UPLOAD EVENTS (tail $LINES dòng) ────"
grep -n "BG_UPLOAD\|FINISH_UPLOAD\|START_UPLOAD\|UPLOAD_CHUNK" "$LOG" | tail -$LINES

echo ""
echo "──── 3. LOG LIÊN QUAN ĐƠN $ORDER ────"
grep -n "$ORDER" "$LOG" | tail -50

echo ""
echo "──── 4. LỖI OAUTH / GDRIVE ────"
grep -n -iE "gdrive|oauth|pydrive|GoogleAuth|Refresh\(\)|access_token|refresh_token" "$LOG" | grep -iE "error|fail|exception|expired|invalid|revok" | tail -50

echo ""
echo "──── 5. EXCEPTION TRACEBACK gần BG_UPLOAD ────"
# Lấy số dòng của các BG_UPLOAD fatal
grep -n "BG_UPLOAD fatal\|BG_UPLOAD.*fail\|BG_UPLOAD refresh" "$LOG" | tail -20 | while IFS=: read lineno rest; do
    echo ""
    echo "  --- Traceback tại dòng $lineno ---"
    # In 30 dòng tiếp theo từ vị trí lỗi
    sed -n "${lineno},$((lineno + 30))p" "$LOG"
done

echo ""
echo "──── 6. THỐNG KÊ UPLOAD THEO NGÀY ────"
echo "  START_UPLOAD theo ngày:"
grep "START_UPLOAD" "$LOG" | grep -oP "\d{4}-\d{2}-\d{2}" | sort | uniq -c | sort -rn | head -20
echo ""
echo "  FINISH_UPLOAD theo ngày:"
grep "FINISH_UPLOAD" "$LOG" | grep -oP "\d{4}-\d{2}-\d{2}" | sort | uniq -c | sort -rn | head -20
echo ""
echo "  BG_UPLOAD ok (thành công) theo ngày:"
grep "BG_UPLOAD ok" "$LOG" | grep -oP "\d{4}-\d{2}-\d{2}" | sort | uniq -c | sort -rn | head -20

echo ""
echo "──── 7. TEMP FILES CÒN TRONG /tmp/pack_streams ────"
if [ -d "/tmp/pack_streams" ]; then
    echo "  Tổng số files: $(ls /tmp/pack_streams/ 2>/dev/null | wc -l)"
    echo "  Dung lượng   : $(du -sh /tmp/pack_streams/ 2>/dev/null | cut -f1)"
    echo "  Meta files   : $(ls /tmp/pack_streams/*.meta.json 2>/dev/null | wc -l) sessions chưa finish"
    echo ""
    echo "  Chi tiết meta files (10 mới nhất):"
    ls -lt /tmp/pack_streams/*.meta.json 2>/dev/null | head -10 | while read perm links owner group size month day hhmm fname; do
        pid=$(python3 -c "import json; d=json.load(open('$fname')); print(d.get('picking_id',0))" 2>/dev/null || echo "?")
        lidx=$(python3 -c "import json; d=json.load(open('$fname')); print(d.get('last_index','?'))" 2>/dev/null || echo "?")
        webm="${fname/.meta.json/.webm}"
        sz=""
        [ -f "$webm" ] && sz=$(du -sh "$webm" 2>/dev/null | cut -f1)
        echo "    $month $day $hhmm  picking_id=$pid  last_index=$lidx  size=$sz  $(basename $fname)"
    done
else
    echo "  /tmp/pack_streams không tồn tại"
fi

echo ""
echo "$SEP"
echo "  DONE. Để xem log realtime:"
echo "    tail -f $LOG | grep -iE 'BG_UPLOAD|FINISH_UPLOAD|START_UPLOAD'"
echo "$SEP"
