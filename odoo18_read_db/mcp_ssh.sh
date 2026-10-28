#!/usr/bin/env bash
# Lệnh cưỡng bức (forced command) của user dbmcp: mỗi kết nối SSH từ Claude Desktop chạy đúng một
# MCP Postgres trên stdio, nối DB đọc bằng role claude_ro (chỉ SELECT). Key không mở được shell.
# add_mcp_user.sh cài file này vào /usr/local/bin/odoo18-read-mcp.
set -euo pipefail

# Odoo lưu ngày giờ dạng UTC không kèm múi giờ. node-postgres đọc kiểu đó theo múi giờ của tiến
# trình — server để giờ VN thì 01:34 UTC bị hiểu là 01:34 VN và trả ra 18:34Z hôm trước (lệch 7 tiếng).
export TZ=UTC

# Mật khẩu qua biến môi trường, không đặt trong URL: đối số tiến trình thì user khác trên máy thấy được.
PGPASSWORD=$(cat /etc/odoo18-read-db/claude_ro.password)
export PGPASSWORD
exec npx -y @modelcontextprotocol/server-postgres@0.6.2 "postgresql://claude_ro@127.0.0.1:5432/odoo18_read"
