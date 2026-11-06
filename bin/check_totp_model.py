# Kiểm model 2FA (auth_totp) trước khi làm module admin giữ khoá 2FA của nhân viên:
#   1. Cột totp_secret có thật, bao nhiêu user đã bật 2FA, dạng secret có đúng base32 không.
#   2. totp_secret đọc được bằng sudo() không (field khai groups=NO_ACCESS), thử sinh mã 6 số từ secret.
#   3. Các method / view / action mà module sẽ bám vào còn đúng tên ở bản đang chạy.
#   4. Model transient / nhóm sẽ dùng.
# CHỈ ĐỌC — không ghi gì. Không in secret (chỉ in độ dài + 2 ký tự đầu để đối chiếu).
# CÁCH CHẠY: copy TOÀN BỘ file dán vào `odoo-bin shell` (notebook Odoo-shell).
exec(r'''
import base64
from odoo.addons.auth_totp.models.totp import TOTP, ALGORITHM, DIGITS, TIMESTEP

def say(level, text):
    print("  [%s] %s" % (level, text))

Users = env["res.users"]

print("\n=== 1. Cột + số user bật 2FA")
env.cr.execute("SELECT count(*) FILTER (WHERE totp_secret IS NOT NULL AND totp_secret <> ''), count(*) FROM res_users")
on, total = env.cr.fetchone()
say("OK", "%s / %s user có totp_secret" % (on, total))
fld = Users._fields["totp_secret"]
say("OK", "totp_secret groups=%r compute=%r" % (fld.groups, fld.compute))

print("\n=== 2. Đọc bằng sudo + sinh mã thử")
sample = Users.sudo().search([("totp_enabled", "=", True)], limit=3)
if not sample:
    say("CẢNH BÁO", "chưa có user nào bật 2FA — không thử được đọc secret")
for u in sample:
    secret = u.sudo().totp_secret
    try:
        key = base64.b32decode(secret)
        say("OK", "%s: secret dài %s, bắt đầu %s…, b32decode được (%s byte)" % (u.login, len(secret), secret[:2], len(key)))
    except Exception as e:
        say("LỖI", "%s: secret không phải base32: %s" % (u.login, e))
print("  ALGORITHM=%s DIGITS=%s TIMESTEP=%s" % (ALGORITHM, DIGITS, TIMESTEP))

print("\n=== 3. Method / view / action module sẽ bám")
for m in ("action_totp_enable_wizard", "action_totp_disable", "_totp_check", "_totp_try_setting", "revoke_all_devices", "_revoke_all_devices"):
    say("OK" if hasattr(Users, m) else "LỖI", "res.users.%s" % m)
for xid in ("auth_totp.view_totp_form", "auth_totp.view_totp_field", "base.view_users_form", "base.view_users_form_simple_modif"):
    rec = env.ref(xid, raise_if_not_found=False)
    say("OK" if rec else "LỖI", "%s" % xid)
for xid in ("auth_totp.view_totp_form", "auth_totp.view_totp_field"):
    rec = env.ref(xid, raise_if_not_found=False)
    if rec:
        arch = rec.arch_db
        for name in ("action_totp_enable_wizard", "action_totp_disable"):
            say("OK" if "name=\"%s\"" % name in arch else "LỖI", "%s có button %s" % (xid, name))
act = env["ir.actions.server"].search([("code", "ilike", "action_totp_disable")])
say("OK", "server action gọi action_totp_disable: %s" % ", ".join(act.mapped("name")) if act else "không có server action nào gọi")

print("\n=== 4. Nhóm / model")
say("OK" if env.ref("base.group_system", raise_if_not_found=False) else "LỖI", "base.group_system")
say("OK" if "auth_totp.wizard" in env else "LỖI", "model auth_totp.wizard (wizard cấp 2FA của core)")
mod = env["ir.module.module"].search([("name", "in", ["auth_totp", "hlv_login_approval"])])
for m in mod:
    print("  module %s: %s %s" % (m.name, m.state, m.latest_version))
''')
