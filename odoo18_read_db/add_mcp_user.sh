#!/usr/bin/env bash
# Cho một máy chạy Claude Desktop dùng MCP Postgres chỉ đọc trên DB odoo18_read, qua SSH.
# Máy đó không cần mở đường hầm hay giữ mật khẩu DB: SSH vào user dbmcp chỉ chạy được mcp_ssh.sh.
#
#   bash add_mcp_user.sh 'ssh-ed25519 AAAA... ' <ten-may>      # chạy bằng root, trong thư mục này
#
# Chạy lại với khoá khác để thêm máy. Chặn một máy: xoá dòng có <ten-may> trong
# /home/dbmcp/.ssh/authorized_keys.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Chạy bằng root."; exit 1; }

PUBKEY=${1:?"Cần khoá public SSH của máy đó (dòng ssh-ed25519 …)"}
LABEL=${2:?"Cần tên ghi chú cho máy, vd. may-sep"}
read -r KTYPE KDATA _ <<< "$PUBKEY"
case "$KTYPE" in ssh-ed25519|ssh-rsa|ecdsa-sha2-*) ;; *) echo "Không giống khoá public SSH: $KTYPE"; exit 1 ;; esac

SRC="$(cd "$(dirname "$0")" && pwd)"
SECRET_DIR=/etc/odoo18-read-db
MCP_BIN=/usr/local/bin/odoo18-read-mcp
KEYS=/home/dbmcp/.ssh/authorized_keys

apt-get install -y -q nodejs npm

# Shell phải là bash (sshd chạy forced command qua shell của user); lệnh vẫn bị khoá bởi command=.
id dbmcp >/dev/null 2>&1 || adduser --disabled-password --gecos "" --shell /bin/bash dbmcp

# Mật khẩu claude_ro chỉ root và dbmcp đọc được.
install -d -m 750 -o root -g dbmcp "$SECRET_DIR"
install -m 640 -o root -g dbmcp /root/claude_ro.password "$SECRET_DIR/claude_ro.password"
install -m 755 -o root -g root "$SRC/mcp_ssh.sh" "$MCP_BIN"

install -d -m 700 -o dbmcp -g dbmcp /home/dbmcp/.ssh
touch "$KEYS" && chown dbmcp:dbmcp "$KEYS" && chmod 600 "$KEYS"
if grep -qF "$KDATA" "$KEYS"; then
    echo "Khoá này đã có — giữ nguyên."
else
    # restrict: không shell, không chuyển tiếp cổng, không agent; command=: chỉ chạy MCP.
    echo "command=\"$MCP_BIN\",restrict $KTYPE $KDATA $LABEL" >> "$KEYS"
fi

# Tải sẵn gói MCP vào cache của dbmcp để lần kết nối đầu từ Claude Desktop không phải chờ tải.
runuser -u dbmcp -- npx -y @modelcontextprotocol/server-postgres@0.6.2 < /dev/null > /dev/null 2>&1 || true

cat <<EOF

Xong. Trên máy chạy Claude Desktop, thêm vào claude_desktop_config.json (mục "mcpServers"):

    "odoo18-read": {
      "command": "ssh",
      "args": ["-T", "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30",
               "dbmcp@$(curl -4 -s --max-time 5 ifconfig.me || echo IP_SERVER)"]
    }

rồi tắt hẳn và mở lại Claude Desktop.
EOF
