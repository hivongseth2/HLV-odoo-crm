# Phần dùng chung của full_refresh.sh (kéo qua SSH) và load_backup.sh (nạp file backup tải tay):
# cấu hình, khoá, và bước hoàn tất một DB vừa nạp rồi đổi tên nó thành RAW_DB.
# File này được source, không chạy riêng.

umask 077   # dump / backup chứa dữ liệu khách hàng — chỉ user đồng bộ đọc được

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/raw_db.env"
mkdir -p -m 700 "$WORK_DIR"

NEW_DB="${RAW_DB}_new"
OLD_DB="${RAW_DB}_old"

# Bảng chỉ giữ cấu trúc, bỏ dữ liệu: log, hàng đợi, phiên, file đính kèm, embedding, bảng chứa bí mật.
# Mẫu theo cú pháp pg_dump (* = chuỗi bất kỳ).
EXCLUDE_DATA=(
    bus_bus bus_presence ir_logging ir_attachment mail_mail res_device_log res_users_log
    'amis_*log*' 'amis_*sync_job*' amis_webhook_queue misa_sync_queue wordpress_sync_queue
    ir_config_parameter res_users_apikeys auth_totp_device auth_totp_rate_limit_log
    ir_mail_server fetchmail_server iap_account payment_provider payment_token
    llm_knowledge_chunk_embedding
)

log() { echo "$(date '+%F %T') $*"; }

local_psql() { psql -X -q -v ON_ERROR_STOP=1 "$@"; }

db_exists() { [ "$(psql -XAt -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$1'")" = "1" ]; }

# incremental_sync.py dùng cùng khoá — không chạy chồng.
take_lock() {
    exec 9>"$WORK_DIR/sync.lock"
    flock 9
}

# Tên các bảng nóng, cách nhau bằng dấu cách (bỏ comment / dòng trống của hot_tables.txt).
hot_tables() { sed 's/#.*//' "$HERE/hot_tables.txt" | xargs; }

# Regex tên cột bí mật — dòng không phải comment đầu tiên của secret_columns.txt.
secret_regex() { grep -v '^[[:space:]]*#' "$HERE/secret_columns.txt" | grep -m1 .; }

recreate_new_db() {
    if db_exists "$NEW_DB"; then dropdb "$NEW_DB"; fi
    createdb "$NEW_DB"
}

# Hoàn tất NEW_DB rồi đổi tên thành RAW_DB. $1 = mốc UTC trên prd mà dữ liệu đã có đến;
# incremental_sync.py đọc tiếp từ mốc này. Bản nạp hỏng (thiếu đơn bán) thì dừng, giữ bản cũ.
finish_new_db() {
    local snapshot_at=$1 rows patterns
    rows=$(psql -XAt -d "$NEW_DB" -c "SELECT count(*) FROM sale_order" 2>/dev/null || echo 0)
    if [ "${rows:-0}" -lt 1000 ]; then
        log "Bản nạp hỏng (sale_order = ${rows:-0} dòng) — giữ bản cũ, không đổi."
        exit 1
    fi

    local_psql -d "$NEW_DB" -v secret_re="$(secret_regex)" -f "$HERE/post_restore.sql"

    # Bản kéo bằng pg_dump đã bỏ sẵn dữ liệu các bảng này; file backup tải tay thì chưa.
    # Đổi mẫu pg_dump sang LIKE: "_" là ký tự đại diện của LIKE nên phải escape.
    patterns=$(printf '%s\n' "${EXCLUDE_DATA[@]}" | sed 's/_/\\_/g; s/\*/%/g' | paste -sd' ')
    local_psql -d "$NEW_DB" -v patterns="$patterns" <<'SQL'
SELECT format('TRUNCATE %I', c.relname)
FROM pg_class c
WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace
  AND c.relname LIKE ANY (string_to_array(:'patterns', ' ')) \gexec
SQL

    local_psql -d "$NEW_DB" -v snapshot_at="$snapshot_at" <<'SQL'
INSERT INTO sync.meta (snapshot_at) VALUES (:'snapshot_at');
SQL
    local_psql -d "$NEW_DB" -v dbname="$NEW_DB" -f "$HERE/claude_ro.sql"

    # Chặn kết nối mới vào bản cũ trước khi ngắt, để không ai chen vào giữa lúc đổi tên.
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

    log "Xong: $RAW_DB có dữ liệu prd đến $snapshot_at UTC (sale_order $rows dòng)"
}
