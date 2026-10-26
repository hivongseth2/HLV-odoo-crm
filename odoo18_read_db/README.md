# odoo18_read_db — DB đọc riêng cho agent

Bản sao Postgres "thô" của DB prd (Odoo.sh), đặt trên server riêng, để agent (Claude…) truy vấn
SQL thoải mái mà không chiếm worker Odoo của prd.

- **Lần đầu** — `load_backup.sh`: nạp file backup tải tay từ Odoo.sh.
- **Mỗi đêm** — `full_refresh.sh`: `pg_dump` prd qua SSH → restore vào DB tạm → đổi tên thành `odoo18_read`.
  Đồng bộ luôn cấu trúc (prd deploy thêm/bỏ field) và dòng bị xoá.
- **Mỗi 5 phút** — `incremental_sync.py`: các bảng trong `hot_tables.txt`, lấy dòng có
  `write_date` mới bằng `COPY` qua SSH, upsert theo `id`. Chỉ chạm Postgres prd (vài truy vấn nhỏ).
- Agent đọc bằng role `claude_ro`: chỉ đọc, giới hạn thời gian mỗi câu, không thấy bảng bí mật.

Dữ liệu khách hàng (tên, điện thoại, địa chỉ) **được giữ** — agent cần để điều phối giao hàng.
Mật khẩu, token, khoá API bị bỏ lúc dump hoặc xoá trắng sau restore (`post_restore.sql`), và lượt
5 phút không chép lại chúng — tên cột coi là bí mật khai một chỗ ở `secret_columns.txt`.

## Cài đặt (Ubuntu 24.04, một lần)

Chép thư mục `odoo18_read_db` lên server rồi chạy bằng root:

```bash
cd odoo18_read_db && bash setup.sh
```

`setup.sh` (chạy lại không hỏng) cài PostgreSQL 16 **chỉ nghe localhost**, tạo user hệ thống
`odoo18read` + các thư mục quyền 700, role Postgres `odoo18read` (dựng/đồng bộ DB) và `claude_ro`
(chỉ đọc, `statement_timeout` 60s, tối đa 5 kết nối; mật khẩu ở `/root/claude_ro.password`),
khoá SSH và `~/.ssh/config` (host `odoosh-prd`) cho `odoo18read`. Cuối script in các bước tay còn lại.

Postgres trong Docker (nếu có) không mở 5432 ra máy chủ nên không đụng Postgres cài thẳng này.

## Nạp lần đầu — file backup tải tay

Odoo.sh → BACKUPS → tải bản **Neutralized + Without filestore** (DB thô không chạy Odoo nên phần bị
neutralize không ảnh hưởng). Chép `.zip` vào `/var/lib/odoo18-read-db`, `chown odoo18read`, rồi:

```bash
runuser -u odoo18read -- /opt/odoo18-read-db/scripts/load_backup.sh /var/lib/odoo18-read-db/<file>.zip
```

Mốc bắt đầu đồng bộ = `write_date` mới nhất trong các bảng nóng của bản backup; lượt 5 phút đầu
tiên kéo mọi thay đổi trên prd từ đó. Xoá file `.zip` sau khi nạp — nó còn nguyên key tích hợp.

## SSH tới prd (cho cập nhật về sau)

Odoo.sh nhận SSH theo **khoá public trên GitHub** của tài khoản có quyền vào nhánh prd — thêm
`/opt/odoo18-read-db/.ssh/id_ed25519.pub` (setup.sh in ra) vào GitHub đó. Khoá này mở được shell prd, nên
chỉ user `odoo18read` đọc được. `ControlMaster` giữ một kết nối dùng lại cho ~30 lệnh mỗi lượt. Thử:

```bash
runuser -u odoo18read -- ssh odoosh-prd 'bash -lc "psql -XAtc \"select 1\""'
```

Mã `20926417` trùng tên DB prd; sau lần deploy prd tới, chạy lại lệnh thử ở trên — nếu Odoo.sh đổi
mã thì sửa `User` trong `/opt/odoo18-read-db/.ssh/config` và `REMOTE_DB` trong `raw_db.env`.

## Chạy định kỳ

Thử một lượt `incremental_sync.py` bằng tay trước. Cron của `odoo18read` (`crontab -u odoo18read -e`), giờ theo múi giờ server:

```
*/5 * * * * /opt/odoo18-read-db/scripts/incremental_sync.py >> /var/log/odoo18-read-db/incremental.log 2>&1
30 2 * * *  /opt/odoo18-read-db/scripts/full_refresh.sh     >> /var/log/odoo18-read-db/full.log 2>&1
```

Hai script dùng chung khoá `WORK_DIR/sync.lock`: lúc chép đêm, lượt 5 phút tự bỏ qua.

## Giới hạn đã biết

- **Trễ**: bảng nóng ≤ 5 phút; mọi bảng khác và dòng bị xoá — đến lần chép đêm.
- **SQL thô không cập nhật `write_date`** thì lượt 5 phút không thấy, chờ chép đêm. Hiện có:
  đổi vị trí phiếu/move trong `deltatech_picking_transit` và `hlv_mobile_barcode` (đổi
  `location_id` / `location_dest_id`), `reserved_quantity` trong `hlv_priority_stock_reservation`.
- **Nâng cấp module tính lại cả bảng** (đổi `write_date` mọi dòng) → lượt 5 phút sau đó kéo lại
  cả bảng. Bảng lớn nhất ~100 MB nên vẫn ổn.
- DB thô **không có khoá ngoại / unique** (bỏ để nhận upsert theo từng bảng) — chỉ dùng để đọc.
- Field compute không lưu (vd. tồn kho tính sẵn trên sản phẩm) không có trong DB — tự tính từ
  `stock_quant`.
