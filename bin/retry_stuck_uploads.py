# -*- coding: utf-8 -*-
"""
retry_stuck_uploads.py
======================
Upload lại tất cả video bị kẹt trong /tmp/pack_streams sau khi OAuth đã được cấp lại.

BƯỚC 1: Vào Odoo > Settings > Google Drive > nhấn Re-authorize (lấy token mới)
BƯỚC 2: Chạy script này:

    python odoo-bin shell -d <TEN_DATABASE> < bin/retry_stuck_uploads.py

Script sẽ:
  - Đọc toàn bộ *.meta.json trong STREAM_DIR
  - Với mỗi session: tìm picking_id (từ meta hoặc dò theo timestamp), upload webm lên Drive
  - Sau khi upload xong: xóa file tạm, post message lên picking (nếu tìm được)
  - In progress + kết quả
"""

import os, json, glob, tempfile, time, traceback, uuid
from datetime import datetime

STREAM_DIR = os.path.join(tempfile.gettempdir(), 'pack_streams')
SEP = "=" * 72

# ── Lọc theo tháng/năm ──
FILTER_YEAR  = 2026   # <-- đổi nếu cần
FILTER_MONTH = 5      # <-- đổi nếu cần (None = không lọc)

def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

# ─────────────────────────────────────────────────────────────
# Import thư viện upload
# ─────────────────────────────────────────────────────────────
try:
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    from oauth2client.client import OAuth2Credentials
    HAS_PYDRIVE = True
except ImportError:
    HAS_PYDRIVE = False
    print("❌ Chưa cài pydrive2: pip install pydrive2 oauth2client")

# ─────────────────────────────────────────────────────────────
# Đọc config từ DB
# ─────────────────────────────────────────────────────────────
ICP = env['ir.config_parameter'].sudo()

def _get(k): return ICP.get_param(k) or ''

creds_json  = _get('gdrive.user_credentials_json')
cid         = _get('gdrive.oauth_client_id')
csec        = _get('gdrive.oauth_client_secret')
redir       = _get('gdrive.oauth_redirect_uri')
scopes_line = _get('gdrive.oauth_scopes') or 'https://www.googleapis.com/auth/drive.file'
anyone_link = _get('gdrive.anyone_link').lower() == 'true'
mapping_str = _get('gdrive.warehouse_folder_mapping') or 'TSN:KHO_HCM,KBC:KHO_BENCAM'

section("0. KIỂM TRA TIỀN ĐỀ")

if not HAS_PYDRIVE:
    print("ABORT: cần pydrive2"); raise SystemExit(1)
if not creds_json:
    print("❌ ABORT: gdrive.user_credentials_json trống – cần Re-authorize trước!"); raise SystemExit(1)
if not cid or not csec:
    print("❌ ABORT: thiếu client_id / client_secret"); raise SystemExit(1)

# Test token ngay lúc này
import json as _json
try:
    creds_data = _json.loads(creds_json)
    if not creds_data.get('refresh_token'):
        print("❌ ABORT: Không có refresh_token – cần Re-authorize lại!"); raise SystemExit(1)
    print(f"✅ refresh_token: <SET>")
    print(f"✅ access_token expires: {creds_data.get('token_expiry', 'N/A')}")
except Exception as ex:
    print(f"❌ ABORT: credentials_json không hợp lệ: {ex}"); raise SystemExit(1)

# ─────────────────────────────────────────────────────────────
# Khởi tạo GoogleDrive một lần dùng cho toàn session
# ─────────────────────────────────────────────────────────────
G_AUTH_URI   = "https://accounts.google.com/o/oauth2/v2/auth"
G_TOKEN_URI  = "https://oauth2.googleapis.com/token"
G_REVOKE_URI = "https://oauth2.googleapis.com/revoke"

def _write_settings(path):
    scopes = [s.strip() for s in scopes_line.replace(',', ' ').split() if s.strip()] \
             or ['https://www.googleapis.com/auth/drive.file']
    content = (
        "client_config_backend: settings\n"
        "client_config:\n"
        f'  client_id: "{cid}"\n'
        f'  client_secret: "{csec}"\n'
        f'  redirect_uri: "{redir}"\n'
        f'  auth_uri: "{G_AUTH_URI}"\n'
        f'  token_uri: "{G_TOKEN_URI}"\n'
        f'  revoke_uri: "{G_REVOKE_URI}"\n'
        "oauth_scope:\n"
        + '\n'.join(f'  - {s}' for s in scopes) + "\n"
        "get_refresh_token: True\n"
        "save_credentials: False\n"
    )
    with open(path, 'w') as f: f.write(content)

set_path = os.path.join(STREAM_DIR, f'retry_settings_{uuid.uuid4().hex}.yaml')
_write_settings(set_path)

gauth = GoogleAuth(set_path)
gauth.credentials = OAuth2Credentials.from_json(creds_json)

print("\nKiểm tra / làm mới OAuth token...")
try:
    if gauth.access_token_expired:
        print("  → Token expired, đang Refresh()...")
        gauth.Refresh()
        # Lưu token mới vào DB
        new_json = gauth.credentials.to_json()
        ICP.set_param('gdrive.user_credentials_json', new_json)
        env.cr.commit()
        print("  ✅ Refresh OK, đã lưu token mới")
    gauth.Authorize()
    print("  ✅ Authorize OK")
except Exception as ex:
    traceback.print_exc()
    print(f"\n❌ ABORT: OAuth thất bại: {ex}")
    print("   → Cần vào Odoo > Settings > GDrive > Re-authorize trên trình duyệt")
    try: os.remove(set_path)
    except: pass
    raise SystemExit(1)

drive = GoogleDrive(gauth)

# ─────────────────────────────────────────────────────────────
# Helper tạo folder Drive
# ─────────────────────────────────────────────────────────────
_folder_cache = {}

def _get_or_create_folder(name, parent_id=None):
    key = (name, parent_id)
    if key in _folder_cache:
        return _folder_cache[key]
    q = "mimeType='application/vnd.google-apps.folder' and trashed=false and title='%s'" % name.replace("'", "\\'")
    if parent_id:
        q += f" and '{parent_id}' in parents"
    found = drive.ListFile({'q': q}).GetList()
    if found:
        fid = found[0]['id']
    else:
        meta = {'title': name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_id: meta['parents'] = [{'id': parent_id}]
        f = drive.CreateFile(meta)
        f.Upload()
        fid = f['id']
    _folder_cache[key] = fid
    return fid

# Warehouse mapping
warehouse_map = {}
for item in mapping_str.split(','):
    if ':' in item:
        k, v = item.strip().split(':', 1)
        warehouse_map[k.strip()] = v.strip()

def _san(s):
    return (s or '').replace('/', '_').replace('\\', '_').replace(' ', '_')

# ─────────────────────────────────────────────────────────────
# Dò picking cho mỗi meta (picking_id=0 → cần đoán)
# ─────────────────────────────────────────────────────────────
def _find_picking_by_timestamp(created_ts, window_sec=180):
    """
    Tìm picking PACK/OUT hoàn tất trong khoảng [created_ts - window_sec, created_ts + 20 phút].
    Không chính xác 100% nhưng là best-effort khi picking_id=0.
    """
    from datetime import datetime, timedelta
    t_start = datetime.utcfromtimestamp(created_ts - window_sec)
    t_end   = datetime.utcfromtimestamp(created_ts + 1800)  # +30 phút
    picks = env['stock.picking'].sudo().search([
        ('picking_type_id.sequence_code', 'in', ['PACK', 'OUT']),
        ('state', 'in', ['done', 'assigned', 'in_progress']),
        ('date_done', '>=', t_start.strftime('%Y-%m-%d %H:%M:%S')),
        ('date_done', '<=', t_end.strftime('%Y-%m-%d %H:%M:%S')),
    ], order='date_done asc', limit=5)
    return picks

# ─────────────────────────────────────────────────────────────
# Tìm tất cả sessions cần retry
# ─────────────────────────────────────────────────────────────
section("1. TÌM CÁC SESSION CẦN UPLOAD")

if not os.path.exists(STREAM_DIR):
    print("STREAM_DIR không tồn tại, không có gì để retry")
    raise SystemExit(0)

meta_files = sorted(glob.glob(os.path.join(STREAM_DIR, '*.meta.json')))
print(f"Tìm thấy {len(meta_files)} meta.json trong thư mục\n")

# Tính timestamp min/max theo FILTER_YEAR / FILTER_MONTH
if FILTER_MONTH:
    import calendar
    ts_from = datetime(FILTER_YEAR, FILTER_MONTH, 1).timestamp()
    last_day = calendar.monthrange(FILTER_YEAR, FILTER_MONTH)[1]
    ts_to   = datetime(FILTER_YEAR, FILTER_MONTH, last_day, 23, 59, 59).timestamp()
    print(f"  Lọc: chỉ xử lý video trong tháng {FILTER_MONTH:02d}/{FILTER_YEAR}")
    print(f"  Khoảng timestamp: {ts_from:.0f} → {ts_to:.0f}\n")
else:
    ts_from, ts_to = 0, float('inf')

sessions = []
skipped_date = 0
for mf in meta_files:
    try:
        with open(mf) as f:
            m = json.load(f)
        created_ts = m.get('created', 0)

        # Lọc theo tháng
        if not (ts_from <= created_ts <= ts_to):
            skipped_date += 1
            continue

        webm = m.get('path') or mf.replace('.meta.json', '.webm')
        if not os.path.exists(webm):
            print(f"  ⚠️  SKIP {os.path.basename(mf)}: webm không tồn tại ({webm})")
            continue
        size_mb = os.path.getsize(webm) / 1024 / 1024
        if size_mb < 0.01:
            print(f"  ⚠️  SKIP {os.path.basename(mf)}: file quá nhỏ ({size_mb:.2f}MB)")
            continue
        sessions.append(m)
        created_dt = datetime.utcfromtimestamp(created_ts).strftime('%Y-%m-%d %H:%M:%S')
        print(f"  ✅ upload_id={m['path'].split('/')[-1].replace('.webm','')} "
              f"picking_id={m.get('picking_id', 0)} "
              f"created={created_dt} "
              f"last_index={m.get('last_index', '?')} "
              f"size={size_mb:.1f}MB")
    except Exception as ex:
        print(f"  ❌ Lỗi đọc {mf}: {ex}")

if skipped_date:
    print(f"\n  ℹ️  Bỏ qua {skipped_date} session ngoài tháng {FILTER_MONTH:02d}/{FILTER_YEAR}")
print(f"\nTổng số session sẽ upload: {len(sessions)}")

# ─────────────────────────────────────────────────────────────
# Upload từng session
# ─────────────────────────────────────────────────────────────
section("2. BẮT ĐẦU UPLOAD")

ok_count = 0
fail_count = 0

for idx, m in enumerate(sessions, 1):
    webm_path = m.get('path') or ''
    picking_id = int(m.get('picking_id') or 0)
    mimetype   = m.get('mimetype') or 'video/webm'
    created_ts = m.get('created') or 0
    upload_id  = os.path.basename(webm_path).replace('.webm', '') if webm_path else 'unknown'

    print(f"\n[{idx}/{len(sessions)}] upload_id={upload_id}  picking_id={picking_id}  size={os.path.getsize(webm_path)/1024/1024:.1f}MB")

    # ── Tìm picking ──
    picking = None
    if picking_id > 0:
        picking = env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            picking = None

    if not picking and created_ts:
        candidates = _find_picking_by_timestamp(created_ts)
        if candidates:
            picking = candidates[0]
            print(f"  ℹ️  picking_id=0 → đoán picking: {picking.name} (id={picking.id}) theo timestamp")
        else:
            print(f"  ℹ️  picking_id=0 → không đoán được picking, sẽ upload vào KHO_UNKNOWN")

    # ── Chuẩn bị tên file ──
    try:
        if picking and picking.exists():
            wh_code = picking.location_id.warehouse_id.code or ''
            order_name = ''
            try: order_name = picking.sale_id.name or ''
            except: pass
            if not order_name:
                order_name = picking.origin or picking.group_id.name or ''
            origin_pick = env['stock.picking'].sudo().search([
                ('group_id', '=', picking.group_id.id),
                ('picking_type_id.sequence_code', 'like', 'PICK'),
                ('id', '!=', picking.id),
            ], limit=1)
            origin_name = (origin_pick.name or '').replace('/', '_')
        else:
            wh_code = ''
            order_name = 'UNKNOWN'
            origin_name = 'UNKNOWN'
            picking = None

        root_name = warehouse_map.get(wh_code, f'KHO_{wh_code}' if wh_code else 'KHO_UNKNOWN')
        ext = {'video/webm': '.webm', 'video/mp4': '.mp4', 'video/ogg': '.ogg'}.get(mimetype, '.webm')
        ts = datetime.utcfromtimestamp(created_ts).strftime('%Y%m%d_%H%M%S') if created_ts else datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_title = f"RETRY_{_san(order_name)}_{_san(origin_name)}_{_san(picking.name if picking else 'NO_PICK')}_{ts}{ext}"

        day_str = datetime.utcfromtimestamp(created_ts).strftime('%d_%m_%Y') if created_ts else datetime.now().strftime('%d_%m_%Y')

        # ── Upload ──
        root_id = _get_or_create_folder(root_name, None)
        day_id  = _get_or_create_folder(day_str, root_id)
        clip_id = _get_or_create_folder("clip", day_id)

        print(f"  → Uploading: {safe_title}")
        print(f"     Drive path: {root_name}/{day_str}/clip/")

        gfile = drive.CreateFile({'title': safe_title, 'parents': [{'id': clip_id}]})
        if mimetype: gfile['mimeType'] = mimetype
        gfile.SetContentFile(webm_path)
        gfile.Upload()

        fid  = gfile['id']
        link = gfile.get('alternateLink') or f"https://drive.google.com/file/d/{fid}/view"

        if anyone_link:
            try:
                gfile.InsertPermission({'type': 'anyone', 'value': 'me', 'role': 'reader'})
            except Exception:
                pass

        print(f"  ✅ OK: {link}")

        # ── Post message lên picking ──
        if picking and picking.exists():
            from markupsafe import Markup, escape
            body = Markup(
                '📹 [RETRY] Video đóng gói: '
                '<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
            ).format(url=escape(link or ''), title=escape(safe_title or 'Video'))
            picking.message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
            env.cr.commit()
            print(f"  ✅ Đã post message lên picking {picking.name}")

        # ── Xóa file tạm ──
        try: os.remove(webm_path)
        except: pass
        # Xóa meta file tương ứng
        meta_file = webm_path.replace('.webm', '.meta.json')
        try: os.remove(meta_file)
        except: pass

        ok_count += 1

    except Exception:
        traceback.print_exc()
        print(f"  ❌ FAILED upload_id={upload_id}")
        fail_count += 1

# ─────────────────────────────────────────────────────────────
# Cleanup settings file
# ─────────────────────────────────────────────────────────────
try: os.remove(set_path)
except: pass

# ─────────────────────────────────────────────────────────────
# Tóm tắt
# ─────────────────────────────────────────────────────────────
section("3. KẾT QUẢ")
print(f"  ✅ Upload thành công : {ok_count} / {len(sessions)}")
print(f"  ❌ Thất bại          : {fail_count} / {len(sessions)}")
if fail_count > 0:
    print(f"\n  Các file thất bại vẫn còn trong {STREAM_DIR}")
    print(f"  Kiểm tra log server để xem lỗi chi tiết")

print(f"\n{SEP}")
print("  RETRY HOÀN THÀNH")
print(SEP)
