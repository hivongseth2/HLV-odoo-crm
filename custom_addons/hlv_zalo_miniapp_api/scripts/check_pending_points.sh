#!/usr/bin/env bash
#
# Tìm các tài khoản Portal đang bị Mini App hiển thị SAI "Điểm chờ xác nhận"
# (và cả "Điểm khả dụng", vì hai số này lấy từ cùng một chỗ).
#
# NGUYÊN NHÂN — có HAI nhánh rơi, cho ra hai con số sai khác nhau:
#
#   1. `_get_scoped_portal_account()`: SĐT client gửi lên không khớp
#      `portal_phone` nào -> lùi về tài khoản mặc định (hoặc tài khoản đầu
#      tiên). Màn hình hiện điểm của NGƯỜI THU MUA KHÁC.
#
#   2. Công ty chưa có tài khoản Portal nào -> `account` = None ->
#      `_reward_balance()` làm `src = account or root`, lấy
#      `res.partner.loyalty_pending_points` vốn là TỔNG của mọi người thu mua.
#
# Script in cả hai con số để đối chiếu, vì từ phía DB không biết được request
# thật đã rơi vào nhánh nào.
#
# SCRIPT NÀY CHỈ ĐỌC. Không ghi, không sửa gì.
#
# CÁCH DÙNG (chạy trên server Odoo.sh, hoặc máy có psql tới được DB)
#   bash check_pending_points.sh            # psql tự lấy DB mặc định
#   bash check_pending_points.sh <ten_db>
#
set -Eeuo pipefail

DB_NAME="${1:-}"

command -v psql >/dev/null 2>&1 || {
  echo "LỖI: không tìm thấy psql. Chạy script này trên server Odoo." >&2
  exit 1
}

if [ -n "$DB_NAME" ]; then
  PSQL=(psql -d "$DB_NAME")
else
  PSQL=(psql)
fi

"${PSQL[@]}" -v ON_ERROR_STOP=1 <<'SQL'
\pset border 2
\timing off

-- Điểm chờ xác nhận của TỪNG tài khoản, theo đúng công thức trong Odoo:
--   point_type = 'exchange' AND state = 'pending'
CREATE TEMP VIEW v_acc AS
SELECT
    a.id                                  AS account_id,
    a.partner_id,
    a.username,
    a.buyer_name,
    a.portal_phone,
    COALESCE(a.is_default, FALSE)         AS is_default,
    COALESCE(SUM(h.point_amount) FILTER (
        WHERE h.point_type = 'exchange' AND h.state = 'pending'
    ), 0)                                 AS diem_dung
FROM hlv_loyalty_portal_account a
LEFT JOIN hlv_loyalty_history h ON h.account_id = a.id
WHERE a.active
GROUP BY a.id, a.partner_id, a.username, a.buyer_name, a.portal_phone, a.is_default;

-- Tài khoản bị lấy nhầm khi SĐT không khớp: ưu tiên mặc định, rồi tới id nhỏ nhất
CREATE TEMP VIEW v_fallback AS
SELECT DISTINCT ON (partner_id)
    partner_id,
    account_id  AS fb_account_id,
    diem_dung   AS fb_diem
FROM v_acc
ORDER BY partner_id, is_default DESC, account_id ASC;

CREATE TEMP VIEW v_cty AS
SELECT partner_id, COUNT(*) AS so_tai_khoan, SUM(diem_dung) AS tong_cong_ty
FROM v_acc GROUP BY partner_id;

\echo '=== TÀI KHOẢN ĐANG BỊ HIỂN THỊ SAI ==='

SELECT
    p.name                                              AS "Khách hàng",
    COALESCE(NULLIF(v.buyer_name, ''), '(chưa đặt)')    AS "Người thu mua",
    v.username                                          AS "Tên đăng nhập",
    COALESCE(NULLIF(v.portal_phone, ''), '(TRỐNG)')     AS "SĐT đăng nhập",
    c.so_tai_khoan                                      AS "Số TK",
    v.diem_dung                                         AS "Điểm ĐÚNG",
    f.fb_diem                                           AS "Nhánh 1: lấy nhầm TK",
    c.tong_cong_ty                                      AS "Nhánh 2: tổng cty",
    CASE WHEN v.portal_phone IS NULL OR v.portal_phone = ''
         THEN 'SĐT trống -> chắc chắn rơi nhánh 1'
         ELSE 'Cùng công ty nhiều người thu mua'
    END                                                 AS "Ghi chú"
FROM v_acc v
JOIN v_cty      c ON c.partner_id = v.partner_id
JOIN v_fallback f ON f.partner_id = v.partner_id
JOIN res_partner p ON p.id = v.partner_id
WHERE c.so_tai_khoan > 1
  AND (v.diem_dung <> f.fb_diem OR v.diem_dung <> c.tong_cong_ty)
ORDER BY ABS(c.tong_cong_ty - v.diem_dung) DESC, p.name, v.username;

\echo ''
\echo '=== TỔNG KẾT ==='

SELECT
    (SELECT COUNT(*) FROM v_cty WHERE so_tai_khoan > 1)          AS "Công ty nhiều TK",
    (SELECT COUNT(*) FROM v_acc v JOIN v_cty c USING (partner_id)
       WHERE c.so_tai_khoan > 1 AND v.diem_dung <> c.tong_cong_ty) AS "TK lệch so tổng cty",
    (SELECT COUNT(*) FROM v_acc
       WHERE portal_phone IS NULL OR portal_phone = '')          AS "TK thiếu SĐT";
SQL

cat <<'EOF'

Đọc bảng:
  Điểm ĐÚNG             số lẽ ra phải hiện cho người thu mua đó
  Nhánh 1               số sẽ hiện khi SĐT không khớp (lấy nhầm tài khoản khác)
  Nhánh 2               số sẽ hiện khi không xác định được tài khoản nào

Dòng nào có "Điểm ĐÚNG" khác hai cột còn lại là đang hiển thị sai.
Script chỉ đọc, không sửa gì — chạy bao nhiêu lần cũng được.
EOF
