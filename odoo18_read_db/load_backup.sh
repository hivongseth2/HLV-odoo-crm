#!/usr/bin/env bash
# Nạp RAW_DB từ file backup tải tay ở tab BACKUPS của Odoo.sh — dùng cho lần đầu, khi chưa có SSH.
# Từ đó về sau incremental_sync.py (mỗi 5 phút) và full_refresh.sh (mỗi đêm) đi qua SSH.
#
#   load_backup.sh /var/lib/odoo18-read-db/<backup>.zip     # file .zip của Odoo.sh (bên trong có dump.sql)
#   load_backup.sh /var/lib/odoo18-read-db/dump.sql         # hoặc dump.sql đã giải nén
#
# Chọn "Neutralized" + "Without filestore" khi tải: DB thô không chạy Odoo nên phần bị neutralize
# (cron, mail server, cổng thanh toán) không ảnh hưởng, lại bớt được thông tin kết nối thật.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

BACKUP=${1:?"Cần đường dẫn file backup (.zip hoặc dump.sql)"}
[ -r "$BACKUP" ] || { echo "Không đọc được $BACKUP"; exit 1; }
take_lock

log "Nạp $BACKUP → $RAW_DB"
recreate_new_db

# Dump của Odoo là SQL thuần. Không dừng ở lỗi: bảng cần extension không có (vd. vector) chỉ mất
# bảng đó. Khoá ngoại được tạo theo dump rồi post_restore.sql bỏ đi.
case "$BACKUP" in
    *.zip) unzip -p "$BACKUP" dump.sql ;;
    *)     cat "$BACKUP" ;;
esac | psql -X -q -d "$NEW_DB" > /dev/null 2> "$WORK_DIR/restore.err" || true
log "Nạp xong, $(grep -c 'ERROR' "$WORK_DIR/restore.err" || true) lỗi — xem $WORK_DIR/restore.err"

# File backup không ghi giờ chụp: lấy write_date mới nhất của các bảng nóng làm mốc.
# Lượt 5 phút đầu tiên đọc từ mốc này (trừ overlap) nên không sót thay đổi sau lúc backup.
SNAPSHOT_AT=$(psql -XAt -d "$NEW_DB" -v tables="$(hot_tables)" <<'SQL'
SELECT max((xpath('/row/m/text()',
                  query_to_xml(format('SELECT max(write_date) AS m FROM %I', t), false, true, '')))[1]::text::timestamp)
FROM unnest(string_to_array(:'tables', ' ')) AS t
WHERE to_regclass(t) IS NOT NULL;
SQL
)
[ -n "$SNAPSHOT_AT" ] || { log "Không xác định được mốc (bảng nóng trống?) — dừng."; exit 1; }
log "Mốc theo dữ liệu (UTC): $SNAPSHOT_AT"

finish_new_db "$SNAPSHOT_AT"
log "Nhớ xoá $BACKUP — file có dữ liệu khách hàng và key tích hợp chưa được xoá."
