-- Cấp quyền đọc cho role claude_ro trên DB vừa nạp (load_backup.sh gọi mỗi lần nạp,
-- vì DB mới không mang quyền của DB cũ). Bản thân role tạo một lần bằng superuser — xem README.
--   psql -v dbname=<db> -f claude_ro.sql
\set ON_ERROR_STOP on

GRANT CONNECT ON DATABASE :"dbname" TO claude_ro;
-- Quyền mặc định của dump có thể cho mọi role tạo bảng trong public; MCP Postgres lách được
-- giao dịch read-only bằng nhiều câu lệnh, nên chặn ở mức quyền chứ không chỉ dựa vào read-only.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO claude_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO claude_ro;

-- Schema phụ của extension (Odoo.sh để unaccent trong unaccent_schema): index trên res_partner…
-- dùng hàm này, thiếu quyền USAGE thì cả câu SELECT thường cũng lỗi "permission denied for schema".
-- Chỉ cho gọi hàm, không mở thêm bảng (bảng vẫn chỉ được SELECT trong public).
SELECT format('GRANT USAGE ON SCHEMA %I TO claude_ro', nspname)
FROM pg_namespace
WHERE nspname NOT LIKE 'pg\_%' AND nspname NOT IN ('information_schema', 'public', 'sync') \gexec

-- Dữ liệu các bảng này đã bị bỏ lúc dump; thu quyền thêm cho chắc nếu sau này có ai đổi danh sách.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'ir_config_parameter', 'res_users_apikeys', 'auth_totp_device', 'ir_mail_server',
        'fetchmail_server', 'iap_account', 'payment_provider', 'payment_token'
    ] LOOP
        IF to_regclass(t) IS NOT NULL THEN
            EXECUTE format('REVOKE ALL ON %I FROM claude_ro', t);
        END IF;
    END LOOP;
END $$;
