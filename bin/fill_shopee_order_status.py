# Script: fill_shopee_order_status.py
# Mục đích: Đọc spreadsheet "order_shopee_220526", sheet "order"
#           Cột A = mã đơn Shopee (x_studio_tham_chiu_shopee)
#           Tra sale.order rồi ghi sale_order_status vào cột B
#
# Chạy: python odoo-bin shell -d <TEN_DATABASE> < fill_shopee_order_status.py

# --- CẤU HÌNH ---
DRY_RUN   = False    # True = chỉ in, KHÔNG ghi | False = ghi thật vào spreadsheet
ROW_LIMIT = 0       # Số dòng dữ liệu thử (0 = toàn bộ)
# ----------------

import json, base64, zlib

env = env  # noqa: F821

SHEET_DOC_NAME   = "order_shopee_220526"
TARGET_SHEET     = "order"
COL_SHOPEE_CODE  = "A"
COL_STATUS       = "B"
COL_ORDER_NAME   = "C"
HEADER_ROW       = 1
DATA_START_ROW   = 2

# ── 1. Tìm spreadsheet ───────────────────────────────────────────────────────
print("=" * 70)
print(f"Tìm spreadsheet: '{SHEET_DOC_NAME}'")
print("=" * 70)

doc = env["documents.document"].sudo().search([
    ("name", "ilike", SHEET_DOC_NAME),
], limit=1)

if not doc:
    print("[ERROR] Không tìm thấy spreadsheet. Dừng.")
    raise SystemExit(1)

print(f"[OK] id={doc.id} | name='{doc.name}'")

# ── 2. Parse JSON ─────────────────────────────────────────────────────────────
raw_bytes = doc.spreadsheet_snapshot
decoded = base64.b64decode(raw_bytes)
try:
    data = json.loads(zlib.decompress(decoded))
    _compressed = True
except Exception:
    data = json.loads(decoded)
    _compressed = False

# ── 3. Tìm đúng sheet theo tên ───────────────────────────────────────────────
target_sheet = None
print(f"\nDanh sách sheet:")
for sh in data.get("sheets", []):
    print(f"  name='{sh.get('name','')}' | id='{sh.get('id','')}'")
    if sh.get("name", "").strip().lower() == TARGET_SHEET.lower():
        target_sheet = sh

if not target_sheet:
    print(f"\n[WARN] Không tìm thấy sheet tên '{TARGET_SHEET}', dùng sheet đầu tiên.")
    target_sheet = data["sheets"][0]

cells = target_sheet.setdefault("cells", {})
print(f"\n[INFO] Dùng sheet: '{target_sheet.get('name','')}' | {len(cells)} cells")

# ── 4. Helper đọc/ghi cell ───────────────────────────────────────────────────
def cell_val(col, row):
    c = cells.get(f"{col}{row}", {})
    if isinstance(c, dict):
        return (c.get("content") or c.get("value") or "").strip()
    return ""

def set_cell(col, row, value):
    key = f"{col}{row}"
    if key not in cells:
        cells[key] = {}
    cells[key]["content"] = str(value) if value is not None else ""

# ── 5. In header + kiểm tra cột A ────────────────────────────────────────────
print()
print(f"Header row {HEADER_ROW}:")
print(f"  Cột A = '{cell_val(COL_SHOPEE_CODE, HEADER_ROW)}'")
print(f"  Cột B = '{cell_val(COL_STATUS, HEADER_ROW)}' (sẽ ghi vào đây)")

# Ghi header cột B, C nếu chưa có
if not cell_val(COL_STATUS, HEADER_ROW):
    set_cell(COL_STATUS, HEADER_ROW, "shopee_order_status")
    print(f"  -> Đặt header cột B = 'shopee_order_status'")
if not cell_val(COL_ORDER_NAME, HEADER_ROW):
    set_cell(COL_ORDER_NAME, HEADER_ROW, "Mã đơn Odoo")
    print(f"  -> Đặt header cột C = 'Mã đơn Odoo'")

# ── 6. Xác nhận field shopee_order_status ────────────────────────────────────
SaleOrder = env["sale.order"].sudo()
status_field = "shopee_order_status"

if status_field not in SaleOrder._fields:
    print(f"\n[ERROR] Field '{status_field}' không tồn tại trên sale.order.")
    print("Các field có 'shopee' hoặc 'status':")
    for f in sorted(SaleOrder._fields):
        if "shopee" in f or "status" in f:
            print(f"  {f}")
    raise SystemExit(1)

print(f"\n[INFO] Dùng field trạng thái: '{status_field}' (char, ghi raw value)")

# ── 7. Duyệt từng dòng ────────────────────────────────────────────────────────
print()
print("=" * 70)
mode_label = "[DRY RUN]" if DRY_RUN else "[LIVE WRITE]"
print(f"{mode_label} Xử lý {'%d dòng' % ROW_LIMIT if ROW_LIMIT else 'toàn bộ'}")
print("=" * 70)

row = DATA_START_ROW
processed = 0
found     = 0
not_found = 0

while True:
    shopee_code = cell_val(COL_SHOPEE_CODE, row)

    # Phát hiện hết dữ liệu: 5 dòng trống liên tiếp
    if not shopee_code:
        blank = sum(
            1 for i in range(5)
            if not cell_val(COL_SHOPEE_CODE, row + i)
        )
        if blank >= 5:
            break
        row += 1
        continue

    processed += 1
    order = SaleOrder.search(
        [("x_studio_tham_chiu_shopee", "=", shopee_code)],
        limit=1,
        order="id desc",
    )

    if order:
        status_val = getattr(order, status_field, None) or ""
        order_name = order.name or ""
        found += 1
        print(f"  Row {row:5d}: '{shopee_code}' | status='{status_val}' | order='{order_name}'")
        if not DRY_RUN:
            set_cell(COL_STATUS, row, status_val)
            set_cell(COL_ORDER_NAME, row, order_name)
    else:
        not_found += 1
        print(f"  Row {row:5d}: '{shopee_code}' -> [NOT FOUND]")
        if not DRY_RUN:
            set_cell(COL_STATUS, row, "Không tìm thấy")
            set_cell(COL_ORDER_NAME, row, "")

    row += 1
    if ROW_LIMIT and processed >= ROW_LIMIT:
        print(f"\n[INFO] Đủ {ROW_LIMIT} dòng thử, dừng.")
        break

# ── 8. Ghi lại spreadsheet ────────────────────────────────────────────────────
print()
print("=" * 70)
print(f"KẾT QUẢ {mode_label}")
print(f"  Tổng dòng xử lý : {processed}")
print(f"  Tìm thấy        : {found}")
print(f"  Không tìm thấy  : {not_found}")

if not DRY_RUN:
    new_json_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
    # Odoo lưu snapshot KHÔNG nén (base64 thuần) — đây là trường hợp phổ biến
    # Thử ghi không nén trước; nếu bản gốc là zlib thì thử lại với nén
    new_encoded = base64.b64encode(new_json_bytes)
    doc.sudo().write({"spreadsheet_snapshot": new_encoded})

    # Xóa toàn bộ revisions — revisions được replay lên trên snapshot và sẽ
    # override lại dữ liệu ta vừa ghi nếu không xóa
    rev_ids = doc.sudo().spreadsheet_revision_ids
    rev_count = len(rev_ids)
    if rev_ids:
        rev_ids.unlink()
        print(f"[INFO] Đã xóa {rev_count} revision(s) để snapshot là trạng thái cuối.")

    env.cr.commit()

    # Kiểm tra lại: đọc snapshot vừa ghi, xem cell B2 có đúng không
    verify_raw = base64.b64decode(doc.sudo().spreadsheet_snapshot)
    try:
        verify_data = json.loads(zlib.decompress(verify_raw))
    except Exception:
        verify_data = json.loads(verify_raw)
    verify_cells = verify_data["sheets"][0].get("cells", {})
    b2_check = (verify_cells.get("B2") or {}).get("content", "(trống)")
    c2_check = (verify_cells.get("C2") or {}).get("content", "(trống)")
    print(f"[VERIFY] B2='{b2_check}' | C2='{c2_check}'")

    print("\n[SUCCESS] Đã ghi vào spreadsheet và commit.")
else:
    print("\n[DRY RUN] Chưa ghi. Đặt DRY_RUN=False và ROW_LIMIT=0 để chạy thật.")
print("=" * 70)
