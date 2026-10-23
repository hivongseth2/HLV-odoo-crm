#!/usr/bin/env bash
# Chép lại toàn bộ DB prd (Odoo.sh) sang RAW_DB — chạy mỗi đêm.
# Restore vào DB tạm rồi mới đổi tên: trong lúc chép, người đọc vẫn dùng bản cũ; bản chép hỏng
# (thiếu dữ liệu đơn bán) thì giữ nguyên bản cũ. Lần đầu dựng DB thô cũng chạy file này.
set -euo pipefail
umask 077   # dump chứa dữ liệu khách hàng — chỉ user đồng bộ đọc được

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/raw_db.env"
mkdir -p -m 700 "$WORK_DIR"

exec 9>"$WORK_DIR/sync.lock"
flock 9   # incremental_sync.py dùng cùng khoá — không chạy chồng

NEW_DB="${RAW_DB}_new"
OLD_DB="${RAW_DB}_old"
DUMP="$WORK_DIR/prd.dump"

# Bỏ DỮ LIỆU (giữ cấu trúc): log, hàng đợi, phiên, file đính kèm, và bảng chuyên chứa bí mật.
EXCLUDE_DATA=(
    bus_bus bus_presence ir_logging ir_attachment mail_mail res_device_log res_users_log
    'amis_*log*' 'amis_*sync_job*' amis_webhook_queue misa_sync_queue wordpress_sync_queue
    ir_config_parameter res_users_apikeys auth_totp_device auth_totp_rate_limit_log
    ir_mail_server fetchmail_server iap_account payment_provider payment_token
)
# Bỏ hẳn bảng: kiểu vector cần pgvector, và embedding không có ích cho việc đọc.
EXCLUDE_TABLE=(llm_knowledge_chunk_embedding)

log() { echo "$(date '+%F %T') $*"; }

# Chạy lệnh trên container prd qua SSH, trong login shell để có sẵn biến môi trường Postgres.
remote() { ssh -o BatchMode=yes "$SSH_TARGET" "bash -lc $(printf '%q' "$1")"; }

local_psql() { psql -X -q -v ON_ERROR_STOP=1 "$@"; }

db_exists() { [ "$(psql -XAt -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$1'")" = "1" ]; }

log "Bắt đầu chép prd → $RAW_DB"

# Mốc lấy TRƯỚC khi dump: thay đổi xảy ra trong lúc dump sẽ được incremental lấy lại (trùng thì upsert).
SNAPSHOT_AT=$(remote "psql -XAt -d $REMOTE_DB -c \"SELECT (now() AT TIME ZONE 'UTC')::timestamp\"")
log "Mốc prd (UTC): $SNAPSHOT_AT"

dump_cmd=(pg_dump -Fc --no-owner --no-acl -d "$REMOTE_DB")
for t in "${EXCLUDE_DATA[@]}"; do dump_cmd+=("--exclude-table-data=$t"); done
for t in "${EXCLUDE_TABLE[@]}"; do dump_cmd+=("--exclude-table=$t"); done
remote "$(printf '%q ' "${dump_cmd[@]}")" > "$DUMP.part"
mv "$DUMP.part" "$DUMP"
log "Dump xong: $(du -h "$DUMP" | cut -f1)"

if db_exists "$NEW_DB"; then dropdb "$NEW_DB"; fi
createdb "$NEW_DB"

# Không tạo khoá ngoại: DB thô nhận upsert từng bảng, không theo thứ tự quan hệ.
pg_restore -l "$DUMP" | grep -v ' FK CONSTRAINT ' > "$WORK_DIR/restore.list"
if ! pg_restore --no-owner --no-acl -j 4 -L "$WORK_DIR/restore.list" -d "$NEW_DB" "$DUMP" 2> "$WORK_DIR/restore.err"; then
    log "pg_restore báo $(grep -c 'ERROR' "$WORK_DIR/restore.err" || true) lỗi — xem $WORK_DIR/restore.err"
fi

rows=$(psql -XAt -d "$NEW_DB" -c "SELECT count(*) FROM sale_order" 2>/dev/null || echo 0)
if [ "${rows:-0}" -lt 1000 ]; then
    log "Bản chép hỏng (sale_order = ${rows:-0} dòng) — giữ bản cũ, không đổi."
    exit 1
fi

local_psql -d "$NEW_DB" -f "$HERE/post_restore.sql"
local_psql -d "$NEW_DB" -v snapshot_at="$SNAPSHOT_AT" <<'SQL'
INSERT INTO sync.meta (snapshot_at) VALUES (:'snapshot_at');
SQL
local_psql -d "$NEW_DB" -v dbname="$NEW_DB" -f "$HERE/claude_ro.sql"

# Đổi bản mới vào chỗ bản cũ. Chặn kết nối mới vào bản cũ trước khi ngắt, để không ai chen vào.
if db_exists "$OLD_DB"; then dropdb "$OLD_DB"; fi
if db_exists "$RAW_DB"; then
    local_psql -d postgres <<SQL
ALTER DATABASE "$RAW_DB" ALLOW_CONNECTIONS false;
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$RAW_DB' AND pid <> pg_backend_pid();
ALTER DATABASE "$RAW_DB" RENAME TO "$OLD_DB";
SQL
fi
local_psql -d postgres -c "ALTER DATABASE \"$NEW_DB\" RENAME TO \"$RAW_DB\""
if db_exists "$OLD_DB"; then dropdb "$OLD_DB"; fi

log "Xong: $RAW_DB = bản prd lúc $SNAPSHOT_AT UTC (sale_order $rows dòng)"
