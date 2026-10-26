-- Chạy trên DB vừa nạp, TRƯỚC khi đổi tên thành RAW_DB (lib.sh gọi, truyền -v secret_re=...).
-- DB thô chỉ để đọc và nhận upsert từ incremental_sync.py, nên bỏ mọi ràng buộc trừ khoá chính:
-- dữ liệu đến theo từng bảng, không theo thứ tự khoá ngoại, giữ ràng buộc là upsert vỡ.
\set ON_ERROR_STOP on

-- \gexec chạy từng lệnh sinh ra trong transaction riêng: DB có hàng nghìn ràng buộc, gom vào một
-- transaction (khối DO) thì vượt max_locks_per_transaction ("out of shared memory").

-- 1) Bỏ khoá ngoại / unique / check / exclusion — khoá ngoại trước, vì nó có thể trỏ vào ràng buộc
--    unique. Phải làm trước bước xoá bí mật: cột token vừa NOT NULL vừa unique
--    (vd. hlv_vendor_quote_access.access_token) không xoá trắng được khi còn ràng buộc.
SELECT format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', conrelid::regclass, conname)
FROM pg_constraint
WHERE contype IN ('u', 'c', 'x', 'f') AND connamespace = 'public'::regnamespace
ORDER BY contype = 'f' DESC \gexec

-- 2) Index unique không gắn với ràng buộc (Odoo tạo bằng CREATE UNIQUE INDEX), trừ khoá chính.
SELECT format('DROP INDEX IF EXISTS %s', i.indexrelid::regclass)
FROM pg_index i
JOIN pg_class t ON t.oid = i.indrelid AND t.relnamespace = 'public'::regnamespace
WHERE i.indisunique AND NOT i.indisprimary
  AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = i.indexrelid) \gexec

-- 3) Bí mật còn sót trong bảng có giữ dữ liệu: cột chữ có tên khớp secret_columns.txt → NULL.
--    (Bảng chuyên chứa bí mật đã bị bỏ dữ liệu — EXCLUDE_DATA trong lib.sh.) Chỉ bảng thật, không view.
CREATE TEMP VIEW secret_columns AS
SELECT c.table_name, c.column_name, c.is_nullable
FROM information_schema.columns c
JOIN information_schema.tables t
  ON t.table_schema = c.table_schema AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE'
WHERE c.table_schema = 'public'
  AND c.data_type IN ('character varying', 'text', 'jsonb')
  AND c.column_name ~* :'secret_re';

SELECT format('ALTER TABLE %I ALTER COLUMN %I DROP NOT NULL', table_name, column_name)
FROM secret_columns WHERE is_nullable = 'NO' \gexec

SELECT format('UPDATE %I SET %I = NULL WHERE %I IS NOT NULL', table_name, column_name, column_name)
FROM secret_columns \gexec

-- 4) Trạng thái đồng bộ: mốc dữ liệu đã có + mốc từng bảng nóng.
CREATE SCHEMA sync;
CREATE TABLE sync.meta (
    snapshot_at timestamp NOT NULL           -- giờ UTC trên prd mà dữ liệu nạp đã có đến
);
CREATE TABLE sync.state (
    table_name text PRIMARY KEY,
    mark       timestamp NOT NULL,           -- giờ UTC trên prd lúc bắt đầu lần đồng bộ thành công cuối
    rows_last  integer,
    synced_at  timestamp NOT NULL DEFAULT now()
);
