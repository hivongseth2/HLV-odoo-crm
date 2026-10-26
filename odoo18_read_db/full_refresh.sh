#!/usr/bin/env bash
# Chép lại toàn bộ DB prd (Odoo.sh) sang RAW_DB qua SSH — chạy mỗi đêm.
# Restore vào DB tạm rồi mới đổi tên: trong lúc chép, người đọc vẫn dùng bản cũ.
# Lần nạp đầu khi chưa có SSH: dùng load_backup.sh với file backup tải tay.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
take_lock

DUMP="$WORK_DIR/prd.dump"

# Chạy lệnh trên container prd qua SSH, trong login shell để có sẵn biến môi trường Postgres.
remote() { ssh -o BatchMode=yes "$SSH_TARGET" "bash -lc $(printf '%q' "$1")"; }

log "Bắt đầu chép prd → $RAW_DB"

# Mốc lấy TRƯỚC khi dump: thay đổi xảy ra trong lúc dump sẽ được incremental lấy lại (trùng thì upsert).
SNAPSHOT_AT=$(remote "psql -XAt -d $REMOTE_DB -c \"SELECT (now() AT TIME ZONE 'UTC')::timestamp\"")
log "Mốc prd (UTC): $SNAPSHOT_AT"

# Bảng embedding bỏ hẳn (kiểu vector cần pgvector); các bảng khác trong EXCLUDE_DATA chỉ bỏ dữ liệu.
dump_cmd=(pg_dump -Fc --no-owner --no-acl -d "$REMOTE_DB" --exclude-table=llm_knowledge_chunk_embedding)
for t in "${EXCLUDE_DATA[@]}"; do dump_cmd+=("--exclude-table-data=$t"); done
remote "$(printf '%q ' "${dump_cmd[@]}")" > "$DUMP.part"
mv "$DUMP.part" "$DUMP"
log "Dump xong: $(du -h "$DUMP" | cut -f1)"

recreate_new_db
# Không tạo khoá ngoại: DB thô nhận upsert từng bảng, không theo thứ tự quan hệ.
pg_restore -l "$DUMP" | grep -v ' FK CONSTRAINT ' > "$WORK_DIR/restore.list"
if ! pg_restore --no-owner --no-acl -j 4 -L "$WORK_DIR/restore.list" -d "$NEW_DB" "$DUMP" 2> "$WORK_DIR/restore.err"; then
    log "pg_restore báo $(grep -c 'ERROR' "$WORK_DIR/restore.err" || true) lỗi — xem $WORK_DIR/restore.err"
fi

finish_new_db "$SNAPSHOT_AT"
