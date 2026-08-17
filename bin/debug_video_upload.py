# -*- coding: utf-8 -*-
"""
debug_video_upload.py
=====================
Chạy bằng lệnh:
    python odoo-bin shell -d <TEN_DATABASE> < bin/debug_video_upload.py

Hoặc nếu dùng script trực tiếp (có venv):
    python odoo-bin shell -d <TEN_DATABASE> --no-http < bin/debug_video_upload.py

Script này kiểm tra toàn bộ lý do video không upload lên Drive được:
 1. Kiểm tra cấu hình GDrive (token, client_id, secret…)
 2. Kiểm tra file tạm (STREAM_DIR) còn sót hay không
 3. Kiểm tra picking DH125524949231713 có tồn tại, group, sale order…
 4. In toàn bộ message/chatter của picking để xem link video đã có chưa
 5. Thử refresh token GDrive ngay tại đây để xác nhận token còn hợp lệ không
"""

import os, json, tempfile, glob, traceback, sys

ORDER_NAME = "DH125524949235321"   # <-- đổi nếu cần
STREAM_DIR = os.path.join(tempfile.gettempdir(), 'pack_streams')

SEP = "=" * 70

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

# ─────────────────────────────────────────────
# 1. Kiểm tra config GDrive
# ─────────────────────────────────────────────
section("1. CONFIG GDRIVE (ir.config_parameter)")

ICP = env['ir.config_parameter'].sudo()

params = [
    'gdrive.oauth_client_id',
    'gdrive.oauth_client_secret',
    'gdrive.oauth_redirect_uri',
    'gdrive.oauth_scopes',
    'gdrive.user_credentials_json',
    'gdrive.anyone_link',
    'gdrive.warehouse_folder_mapping',
]
config = {}
for p in params:
    v = ICP.get_param(p) or ''
    config[p] = v

# In tóm tắt (ẩn secret)
for k, v in config.items():
    if 'secret' in k or 'credential' in k or 'json' in k:
        display = f"<SET, len={len(v)}>" if v else "<EMPTY>"
    else:
        display = v or "<EMPTY>"
    status = "✅" if v else "❌ MISSING"
    print(f"  {status}  {k} = {display}")

# Phân tích token JSON
creds_json = config.get('gdrive.user_credentials_json', '')
if creds_json:
    try:
        creds = json.loads(creds_json)
        print("\n  --- Token details ---")
        print(f"  token_expiry  : {creds.get('token_expiry', 'N/A')}")
        print(f"  access_token  : {'<SET>' if creds.get('access_token') else '❌ MISSING'}")
        print(f"  refresh_token : {'<SET>' if creds.get('refresh_token') else '❌ MISSING – KHÔNG THỂ REFRESH!'}")
        print(f"  client_id     : {creds.get('client_id', 'N/A')}")
        # Kiểm tra expired
        import datetime
        expiry_str = creds.get('token_expiry', '')
        if expiry_str:
            try:
                # format: "2024-01-01T00:00:00Z" hoặc "2024-01-01T00:00:00.000000Z"
                expiry_str_clean = expiry_str.rstrip('Z').split('.')[0]
                expiry_dt = datetime.datetime.fromisoformat(expiry_str_clean)
                now = datetime.datetime.utcnow()
                if expiry_dt < now:
                    print(f"  ⚠️  TOKEN ĐÃ HẾT HẠN ({expiry_str}) – cần refresh hoặc cấp lại OAuth")
                else:
                    diff = expiry_dt - now
                    print(f"  ✅ Token còn hạn: còn ~{int(diff.total_seconds()//60)} phút")
            except Exception as ex:
                print(f"  ⚠️  Không parse được token_expiry: {ex}")
    except json.JSONDecodeError as ex:
        print(f"  ❌ gdrive.user_credentials_json KHÔNG PHẢI JSON HỢP LỆ: {ex}")
else:
    print("\n  ❌ gdrive.user_credentials_json TRỐNG – đây là nguyên nhân chính!")
    print("     → Cần vào Settings > GDrive > Authorize để cấp OAuth lại")

# ─────────────────────────────────────────────
# 2. Kiểm tra file tạm còn sót
# ─────────────────────────────────────────────
section("2. FILE TẠM TRONG STREAM_DIR")
print(f"  STREAM_DIR = {STREAM_DIR}")
if not os.path.exists(STREAM_DIR):
    print("  ℹ️  Thư mục không tồn tại (chưa có upload nào)")
else:
    all_files = glob.glob(os.path.join(STREAM_DIR, '*'))
    if not all_files:
        print("  ℹ️  Thư mục rỗng – không còn file tạm nào")
    else:
        print(f"  Tìm thấy {len(all_files)} file(s):")
        for fp in sorted(all_files):
            size = os.path.getsize(fp) if os.path.exists(fp) else 0
            mtime = os.path.getmtime(fp) if os.path.exists(fp) else 0
            import datetime
            mt = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            print(f"    [{mt}] {os.path.basename(fp)} ({size/1024:.1f} KB)")

    # Meta files – session upload chưa finish?
    meta_files = glob.glob(os.path.join(STREAM_DIR, '*.meta.json'))
    if meta_files:
        print(f"\n  ⚠️  CÓ {len(meta_files)} PHIÊN UPLOAD CHƯA FINISH:")
        for mf in meta_files:
            try:
                with open(mf) as f:
                    m = json.load(f)
                print(f"    upload_id={os.path.basename(mf).replace('.meta.json','')} picking_id={m.get('picking_id')} last_index={m.get('last_index')} created={m.get('created')}")
            except Exception:
                print(f"    {mf}: không đọc được")

# ─────────────────────────────────────────────
# 3. Tìm picking theo ORDER_NAME
# ─────────────────────────────────────────────
section(f"3. TÌM PICKING / SALE ORDER: {ORDER_NAME}")

# Tìm sale order
sale = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if sale:
    print(f"  ✅ Sale Order: id={sale.id}  name={sale.name}  state={sale.state}")
else:
    # Thử tìm gần đúng
    sale_like = env['sale.order'].sudo().search([('name', 'ilike', ORDER_NAME[-10:])], limit=5)
    if sale_like:
        print(f"  ⚠️  Không tìm thấy exact match, tìm thấy tương tự:")
        for s in sale_like:
            print(f"      id={s.id}  name={s.name}  state={s.state}")
    else:
        print(f"  ❌ Không tìm thấy sale order nào tên: {ORDER_NAME}")

# Tìm pickings liên quan
pickings = env['stock.picking'].sudo().search([
    '|', '|',
    ('name', 'ilike', ORDER_NAME),
    ('origin', 'ilike', ORDER_NAME),
    ('sale_id.name', '=', ORDER_NAME),
], limit=20)

if not pickings and sale:
    pickings = env['stock.picking'].sudo().search([('sale_id', '=', sale.id)], limit=20)

if not pickings:
    print(f"\n  ❌ Không tìm thấy picking nào liên quan đến {ORDER_NAME}")
else:
    print(f"\n  ✅ Tìm thấy {len(pickings)} picking(s) liên quan:")
    for p in pickings:
        wh = p.location_id.warehouse_id
        print(f"\n  ──── Picking: {p.name} (id={p.id}) ────")
        print(f"    state           : {p.state}")
        print(f"    type            : {p.picking_type_id.sequence_code} / {p.picking_type_id.name}")
        print(f"    origin          : {p.origin}")
        print(f"    sale_id         : {p.sale_id.name if p.sale_id else 'N/A'}")
        print(f"    group_id        : {p.group_id.name if p.group_id else 'N/A'}")
        print(f"    warehouse       : {wh.code} – {wh.name}" if wh else "    warehouse       : N/A")
        print(f"    x_pack_start    : {p.x_pack_start_time}")
        print(f"    x_pack_duration : {p.x_pack_actual_duration} phút")

        # Kiểm tra video message
        video_msgs = p.message_ids.filtered(lambda m: 'drive.google.com' in (m.body or '') or '📹' in (m.body or '') or 'Video' in (m.body or ''))
        if video_msgs:
            print(f"\n    ✅ TÌM THẤY {len(video_msgs)} MESSAGE VIDEO:")
            for m in video_msgs:
                print(f"      [{m.date}] {m.body[:200]}")
        else:
            print(f"\n    ❌ KHÔNG CÓ MESSAGE VIDEO – video chưa được upload lên Drive")

# ─────────────────────────────────────────────
# 4. Kiểm tra logs trong mail.message (note) gần đây
# ─────────────────────────────────────────────
section("4. TOÀN BỘ MESSAGES/CHATTER CỦA PICKING LIÊN QUAN")

for p in pickings:
    if p.picking_type_id.sequence_code not in ('PACK', 'OUT', 'PICK'):
        continue
    print(f"\n  Picking {p.name}  (state={p.state}):")
    for m in p.message_ids.sorted('date', reverse=True)[:15]:
        author = m.author_id.name if m.author_id else 'System'
        body_short = (m.body or '').replace('\n', ' ')[:120]
        print(f"    [{m.date}] [{m.message_type}] {author}: {body_short}")

# ─────────────────────────────────────────────
# 5. Thử refresh OAuth token
# ─────────────────────────────────────────────
section("5. THỬ REFRESH GOOGLE OAUTH TOKEN")

if not creds_json:
    print("  Bỏ qua – không có credentials_json")
else:
    try:
        import sys, os
        # Thêm path nếu cần
        try:
            from pydrive2.auth import GoogleAuth
            from oauth2client.client import OAuth2Credentials

            cid   = config.get('gdrive.oauth_client_id', '')
            csec  = config.get('gdrive.oauth_client_secret', '')
            redir = config.get('gdrive.oauth_redirect_uri', '')
            scopes_line = config.get('gdrive.oauth_scopes', 'https://www.googleapis.com/auth/drive.file')

            # Viết settings tạm
            import uuid
            from custom_addons.custom_barcode_scan_redirect.controllers._shared import _write_settings_file, STREAM_DIR, G_AUTH_URI, G_TOKEN_URI

            set_path = os.path.join(STREAM_DIR, f'debug_settings_{uuid.uuid4().hex}.yaml')
            os.makedirs(STREAM_DIR, exist_ok=True)
            _write_settings_file(set_path, cid, csec, redir, scopes_line)

            gauth = GoogleAuth(set_path)
            gauth.credentials = OAuth2Credentials.from_json(creds_json)

            print(f"  access_token_expired = {gauth.access_token_expired}")

            if gauth.access_token_expired:
                print("  → Token đã expired, đang thử Refresh()...")
                gauth.Refresh()
                gauth.Authorize()
                print("  ✅ Refresh thành công!")
                # Lưu lại credentials mới
                new_json = gauth.credentials.to_json()
                ICP.set_param('gdrive.user_credentials_json', new_json)
                env.cr.commit()
                print("  ✅ Đã lưu credentials mới vào database")
            else:
                gauth.Authorize()
                print("  ✅ Token còn hợp lệ, Authorize OK")

            try: os.remove(set_path)
            except: pass

        except ImportError as e:
            print(f"  ⚠️  Không import được pydrive2/oauth2client: {e}")
            print("     Cài: pip install pydrive2 oauth2client")
    except Exception:
        print("  ❌ LỖI KHI THỬ REFRESH TOKEN:")
        traceback.print_exc()

# ─────────────────────────────────────────────
# 6. Gợi ý nguyên nhân & fix
# ─────────────────────────────────────────────
section("6. PHÂN TÍCH NGUYÊN NHÂN & GỢI Ý FIX")

issues = []
if not creds_json:
    issues.append("❌ CRITICAL: gdrive.user_credentials_json trống → chưa cấp OAuth lần nào hoặc đã bị xóa")
elif not json.loads(creds_json).get('refresh_token'):
    issues.append("❌ CRITICAL: Không có refresh_token → token hết hạn không thể tự refresh → vào Settings cấp OAuth lại")

if not config.get('gdrive.oauth_client_id'):
    issues.append("❌ CRITICAL: gdrive.oauth_client_id trống")
if not config.get('gdrive.oauth_client_secret'):
    issues.append("❌ CRITICAL: gdrive.oauth_client_secret trống")

# Có meta file sót → finish_upload chưa được gọi
if os.path.exists(STREAM_DIR):
    meta_files = glob.glob(os.path.join(STREAM_DIR, '*.meta.json'))
    if meta_files:
        issues.append(f"⚠️  Có {len(meta_files)} phiên upload chưa finish (browser đóng trước khi ghi xong?)")

if not pickings:
    issues.append(f"⚠️  Không tìm thấy picking cho đơn {ORDER_NAME}")
else:
    pack_pickings = pickings.filtered(lambda p: 'PACK' in (p.picking_type_id.sequence_code or '').upper() or 'OUT' in (p.picking_type_id.sequence_code or '').upper())
    if not pack_pickings:
        issues.append(f"⚠️  Không có picking PACK/OUT cho đơn {ORDER_NAME} → không có giao diện đóng gói → không có video")

if not issues:
    print("  ✅ Không phát hiện vấn đề rõ ràng. Xem chi tiết phần 1-5 ở trên.")
else:
    for i in issues:
        print(f"  {i}")

print(f"\n  HƯỚNG XỬ LÝ PHỔ BIẾN:")
print(f"  1. NGUYÊN NHÂN HAY GẶP NHẤT: trình duyệt chuyển trang TRƯỚC KHI finish_upload chạy xong")
print(f"     → fix đã được áp dụng: stopRecording() giờ trả về Promise, await trước khi redirect")
print(f"  2. Có meta.json nhưng không có webm → startUpload gọi rồi không quay được")
print(f"  3. Vào Odoo > Settings > Google Drive Integration > nhấn 'Connect / Re-authorize'")
print(f"     nếu credentials_json trống hoặc không có refresh_token")
print(f"  4. Kiểm tra odoo-server.log tìm 'BG_UPLOAD' để xem lỗi exception cụ thể")
print(f"  5. Chạy bin/retry_stuck_uploads.py để upload lại các video bị kẹt")

print(f"\n{SEP}")
print("  SCRIPT HOÀN THÀNH")
print(SEP)
