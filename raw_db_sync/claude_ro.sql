-- Cấp quyền đọc cho role claude_ro trên DB vừa restore (full_refresh.sh gọi mỗi lần chép,
-- vì DB mới không mang quyền của DB cũ). Bản thân role tạo một lần bằng superuser — xem README.
--   psql -v dbname=<db> -f claude_ro.sql
\set ON_ERROR_STOP on

GRANT CONNECT ON DATABASE :"dbname" TO claude_ro;
GRANT USAGE ON SCHEMA public TO claude_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO claude_ro;

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
