-- Chạy trên DB vừa restore, TRƯỚC khi đổi tên thành RAW_DB (full_refresh.sh gọi).
-- DB thô chỉ để đọc và nhận upsert từ incremental_sync.py, nên bỏ mọi ràng buộc trừ khoá chính:
-- dữ liệu đến theo từng bảng, không theo thứ tự khoá ngoại, giữ ràng buộc là upsert vỡ.
\set ON_ERROR_STOP on

-- 1) Bí mật còn sót trong bảng có giữ dữ liệu: mọi cột chữ có tên kiểu mật khẩu / token / khoá.
--    (Bảng chuyên chứa bí mật đã bị bỏ dữ liệu ngay lúc dump — xem EXCLUDE_DATA trong full_refresh.sh.)
DO $$
DECLARE
    c record;
BEGIN
    FOR c IN
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND data_type IN ('character varying', 'text', 'jsonb')
          AND column_name ~* '(password|passwd|secret|token|api_?key|private_key|access_key|signature_key)'
    LOOP
        EXECUTE format('UPDATE %I SET %I = %s WHERE %I IS NOT NULL',
            c.table_name, c.column_name,
            CASE WHEN c.is_nullable = 'YES' THEN 'NULL'
                 WHEN c.data_type = 'jsonb' THEN '''{}''::jsonb'
                 ELSE '''''' END,
            c.column_name);
    END LOOP;
END $$;

-- 2) Bỏ ràng buộc unique / check / exclusion (khoá ngoại đã bị loại khỏi danh sách restore).
DO $$
DECLARE
    c record;
BEGIN
    FOR c IN
        SELECT conrelid::regclass AS tbl, conname
        FROM pg_constraint
        WHERE contype IN ('u', 'c', 'x', 'f') AND connamespace = 'public'::regnamespace
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', c.tbl, c.conname);
    END LOOP;
END $$;

-- 3) Index unique không gắn với ràng buộc (Odoo tạo bằng CREATE UNIQUE INDEX), trừ khoá chính.
DO $$
DECLARE
    c record;
BEGIN
    FOR c IN
        SELECT i.indexrelid::regclass AS idx
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid AND t.relnamespace = 'public'::regnamespace
        WHERE i.indisunique AND NOT i.indisprimary
          AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = i.indexrelid)
    LOOP
        EXECUTE format('DROP INDEX IF EXISTS %s', c.idx);
    END LOOP;
END $$;

-- 4) Trạng thái đồng bộ: mốc chụp bản dump + mốc từng bảng nóng.
CREATE SCHEMA sync;
CREATE TABLE sync.meta (
    snapshot_at timestamp NOT NULL           -- giờ UTC trên prd ngay trước pg_dump
);
CREATE TABLE sync.state (
    table_name text PRIMARY KEY,
    mark       timestamp NOT NULL,           -- giờ UTC trên prd lúc bắt đầu lần đồng bộ thành công cuối
    rows_last  integer,
    synced_at  timestamp NOT NULL DEFAULT now()
);
