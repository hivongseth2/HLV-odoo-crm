#!/usr/bin/env bash
# Cài môi trường cho odoo18_read_db trên Ubuntu 24.04. Chạy bằng root, từ trong thư mục odoo18_read_db.
# Chạy lại không hỏng: cái gì đã có thì giữ (không đổi mật khẩu, không tạo lại khoá SSH).
#
# Postgres cài thẳng lên máy, chỉ nghe localhost:5432 — không đụng các Postgres trong Docker
# (chúng không mở 5432 ra máy chủ). Không cài cron: chạy thử tay trước, xem README.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Chạy bằng root (sudo)."; exit 1; }

SRC="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/odoo18-read-db
WORK=/var/lib/odoo18-read-db
LOGS=/var/log/odoo18-read-db
PG_CONF_D=/etc/postgresql/16/main/conf.d
CLAUDE_PASS_FILE=/root/claude_ro.password

log() { echo "== $*"; }

log "Cài gói"
apt-get update -q
apt-get install -y -q postgresql-16 postgresql-client-16 python3-psycopg2 rsync unzip cron

log "Postgres chỉ nghe localhost"
install -d "$PG_CONF_D"
echo "listen_addresses = 'localhost'" > "$PG_CONF_D/odoo18_read.conf"
systemctl enable postgresql >/dev/null
systemctl restart postgresql

log "User hệ thống odoo18read + thư mục chỉ odoo18read đọc được"
id odoo18read >/dev/null 2>&1 || adduser --system --group --home "$APP" --shell /bin/bash odoo18read
install -d -o odoo18read -g odoo18read -m 700 "$APP" "$APP/.ssh" "$WORK" "$LOGS"
rsync -a --delete --exclude raw_db.env "$SRC/" "$APP/scripts/"
[ -f "$APP/scripts/raw_db.env" ] || cp "$SRC/raw_db.env.example" "$APP/scripts/raw_db.env"
chown -R odoo18read:odoo18read "$APP/scripts"
chmod 700 "$APP/scripts"
chmod +x "$APP/scripts/full_refresh.sh" "$APP/scripts/load_backup.sh" "$APP/scripts/incremental_sync.py"

log "Role Postgres odoo18read (dựng/đồng bộ DB) và claude_ro (chỉ đọc)"
if [ ! -f "$CLAUDE_PASS_FILE" ]; then
    (umask 077; openssl rand -base64 24 | tr -d '/+=' > "$CLAUDE_PASS_FILE")
fi
runuser -u postgres -- psql -X -q -v ON_ERROR_STOP=1 -v claude_pass="$(cat "$CLAUDE_PASS_FILE")" <<'SQL'
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'odoo18read') AS need_odoo18read,
       NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claude_ro') AS need_claude \gset
\if :need_odoo18read
CREATE ROLE odoo18read LOGIN CREATEDB;
\endif
\if :need_claude
CREATE ROLE claude_ro LOGIN PASSWORD :'claude_pass';
\endif
GRANT pg_signal_backend TO odoo18read;
ALTER ROLE claude_ro CONNECTION LIMIT 5;
ALTER ROLE claude_ro SET default_transaction_read_only = on;
ALTER ROLE claude_ro SET statement_timeout = '60s';
SQL

log "Khoá SSH để odoo18read vào shell prd trên Odoo.sh"
KEY="$APP/.ssh/id_ed25519"
[ -f "$KEY" ] || runuser -u odoo18read -- ssh-keygen -q -t ed25519 -N '' -C "odoo18read@$(hostname)" -f "$KEY"
if [ ! -f "$APP/.ssh/config" ]; then
    cat > "$APP/.ssh/config" <<'CFG'
Host odoosh-prd
    HostName hoanglongvu.odoo.com
    User 20926417
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m
    ServerAliveInterval 30
CFG
fi
grep -q hoanglongvu.odoo.com "$APP/.ssh/known_hosts" 2>/dev/null \
    || ssh-keyscan hoanglongvu.odoo.com 2>/dev/null >> "$APP/.ssh/known_hosts"
chown -R odoo18read:odoo18read "$APP/.ssh"
chmod 600 "$APP/.ssh/config" "$APP/.ssh/known_hosts"

log "Xong. Việc còn lại (tay):"
cat <<EOF
NẠP LẦN ĐẦU từ file backup tải tay (Odoo.sh → BACKUPS → tải: Neutralized + Without filestore):
  a) Chép file .zip lên server vào $WORK, rồi:  chown odoo18read:odoo18read $WORK/<file>.zip
  b) runuser -u odoo18read -- $APP/scripts/load_backup.sh $WORK/<file>.zip
  c) Xoá file .zip sau khi nạp xong.

CẬP NHẬT VỀ SAU qua SSH:
1) Thêm khoá public dưới đây vào GitHub của tài khoản có quyền nhánh prd trên Odoo.sh
   (GitHub → Settings → SSH and GPG keys → New SSH key):

$(cat "$KEY.pub")

2) Thử vào prd (chỉ đọc 'select 1'):
   runuser -u odoo18read -- ssh odoosh-prd 'bash -lc "psql -XAtc \"select 1\""'
3) Thử một lượt 5 phút:  runuser -u odoo18read -- $APP/scripts/incremental_sync.py
4) Ổn rồi mới cài cron (5 phút + chép đêm) — xem $APP/scripts/README.md

Mật khẩu role claude_ro (cho MCP Postgres của Claude): $CLAUDE_PASS_FILE
EOF
