#!/usr/bin/env bash
# run_debug_backorder.sh
# Chạy script kiểm tra backorder location trên server/container
#
# Usage:
#   1. Chạy trực tiếp trong container:
#      docker exec -i <container_name> odoo shell -d hoanglongvu-stagin-27232893 --no-http < debug_so_backorder_location.py
#
#   2. Hoặc chạy script này (auto detect container):
#      ./run_debug_backorder.sh
#      ./run_debug_backorder.sh <container_name>   # nếu muốn chỉ định tên

DB="hoanglongvu-stagin-27232893"
SCRIPT="$(dirname "$0")/debug_so_backorder_location.py"

# ── Chọn container ────────────────────────────────────────────────────────────
if [ -n "$1" ]; then
    CONTAINER="$1"
else
    CONTAINER=$(docker ps --format "{{.Names}}" | grep -i odoo | head -1)
fi

if [ -z "$CONTAINER" ]; then
    echo "❌ Không tìm thấy container Odoo. Truyền tên container làm tham số:"
    echo "   $0 <container_name>"
    exit 1
fi

echo "▶ Container : $CONTAINER"
echo "▶ Database  : $DB"
echo "▶ Script    : $SCRIPT"
echo ""

docker exec -i "$CONTAINER" odoo shell -d "$DB" --no-http < "$SCRIPT"
