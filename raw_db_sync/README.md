# raw_db_sync — DB đọc riêng cho agent

Bản sao Postgres "thô" của DB prd (Odoo.sh), đặt trên server riêng, để agent (Claude…) truy vấn
SQL thoải mái mà không chiếm worker Odoo của prd.

- **Mỗi đêm** — `full_refresh.sh`: `pg_dump` prd qua SSH → restore vào DB tạm → đổi tên thành `hlv_raw`.
  Đồng bộ luôn cấu trúc (prd deploy thêm/bỏ field) và dòng bị xoá.
- **Mỗi 5 phút** — `incremental_sync.py`: các bảng trong `hot_tables.txt`, lấy dòng có
  `write_date` mới bằng `COPY` qua SSH, upsert theo `id`. Chỉ chạm Postgres prd (vài truy vấn nhỏ).
- Agent đọc bằng role `claude_ro`: chỉ đọc, giới hạn thời gian mỗi câu, không thấy bảng bí mật.

Dữ liệu khách hàng (tên, điện thoại, địa chỉ) **được giữ** — agent cần để điều phối giao hàng.
Mật khẩu, token, khoá API bị bỏ lúc dump hoặc xoá trắng sau restore (`post_restore.sql`).

## Cài đặt (Ubuntu, một lần)

```bash
sudo apt install postgresql-16 python3-psycopg2
```

Postgres **chỉ nghe localhost** (mặc định của gói Ubuntu: `listen_addresses = 'localhost'`) —
không mở cổng 5432 ra ngoài.

User hệ thống chạy đồng bộ, thư mục chỉ user đó đọc được:

```bash
sudo adduser --system --group --home /opt/hlv_raw rawsync
sudo install -d -o rawsync -g rawsync -m 700 /var/lib/hlv_raw /var/log/hlv_raw
# chép thư mục raw_db_sync vào /opt/hlv_raw/raw_db_sync, chown rawsync
```

Role Postgres (chạy bằng `sudo -u postgres psql`):

```sql
CREATE ROLE rawsync LOGIN CREATEDB;
GRANT pg_signal_backend TO rawsync;          -- để ngắt kết nối vào bản cũ khi đổi bản mới
CREATE ROLE claude_ro LOGIN PASSWORD '<đặt mật khẩu>' CONNECTION LIMIT 5;
ALTER ROLE claude_ro SET default_transaction_read_only = on;
ALTER ROLE claude_ro SET statement_timeout = '60s';
```

## SSH tới prd

Odoo.sh nhận SSH theo **khoá public trên GitHub** của tài khoản có quyền vào nhánh prd.
Khoá này mở được shell prd, nên chỉ đặt trên server này, chỉ user `rawsync` đọc được.

```bash
sudo -u rawsync install -d -m 700 /opt/hlv_raw/.ssh
sudo -u rawsync ssh-keygen -t ed25519 -N '' -f /opt/hlv_raw/.ssh/id_ed25519
# thêm id_ed25519.pub vào GitHub của tài khoản có quyền prd trên Odoo.sh
```

`/opt/hlv_raw/.ssh/config`:

```
Host odoosh-prd
    HostName hoanglongvu.odoo.com
    User 20926417
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m
    ServerAliveInterval 30
```

`ControlMaster` giữ một kết nối dùng lại cho ~30 lệnh mỗi lượt. Thử:

```bash
sudo -u rawsync ssh odoosh-prd 'bash -lc "psql -XAtc \"select 1\""'
```

Mã `20926417` trùng tên DB prd; sau lần deploy prd tới, chạy lại lệnh thử ở trên — nếu Odoo.sh đổi
mã thì sửa `User` ở đây và `REMOTE_DB` trong `raw_db.env`.

## Chạy

```bash
cd /opt/hlv_raw/raw_db_sync
cp raw_db.env.example raw_db.env      # sửa nếu cần
chmod +x full_refresh.sh incremental_sync.py
sudo -u rawsync ./full_refresh.sh      # lần đầu: dựng hlv_raw (vài phút, DB ~2,2 GB)
sudo -u rawsync ./incremental_sync.py  # thử một lượt
```

Cron của `rawsync` (`sudo -u rawsync crontab -e`), giờ theo múi giờ server:

```
*/5 * * * * /opt/hlv_raw/raw_db_sync/incremental_sync.py >> /var/log/hlv_raw/incremental.log 2>&1
30 2 * * *  /opt/hlv_raw/raw_db_sync/full_refresh.sh     >> /var/log/hlv_raw/full.log 2>&1
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
