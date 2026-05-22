# Script: cancel_draft_hddt_not_in_sheet.py
# Mục đích: Hủy toàn bộ meinvoice.invoice đang ở trạng thái "Nháp"
#           mà sale_order_id KHÔNG nằm trong danh sách đơn hàng Shopee
#           từ spreadsheet "order_shopee_220526" (cột A)
#
# Logic: spreadsheet cột A → x_studio_tham_chiu_shopee → sale.order.id
#        Hủy tất cả draft HDDT có sale_order_id KHÔNG thuộc tập đó
#
# Chạy: python odoo-bin shell -d <TEN_DATABASE> < cancel_draft_hddt_not_in_sheet.py

# --- CẤU HÌNH ---
DRY_RUN        = False   # True = chỉ in | False = hủy thật
SHEET_DOC_NAME = "order_shopee_220526"
# ----------------

import json, base64, zlib

env = env  # noqa: F821

# ── 1. Đọc spreadsheet lấy danh sách shopee code ────────────────────────────
print("=" * 70)
print(f"Đọc spreadsheet: '{SHEET_DOC_NAME}'")
print("=" * 70)

doc = env["documents.document"].sudo().search([
    ("name", "ilike", SHEET_DOC_NAME),
], limit=1)

if not doc:
    print("[ERROR] Không tìm thấy spreadsheet.")
    raise SystemExit(1)

raw_bytes = doc.spreadsheet_snapshot
decoded = base64.b64decode(raw_bytes)
try:
    data = json.loads(zlib.decompress(decoded))
except Exception:
    data = json.loads(decoded)

sheet = data["sheets"][0]
cells = sheet.get("cells", {})

def cell_val(col, row):
    c = cells.get(f"{col}{row}", {})
    if isinstance(c, dict):
        return (c.get("content") or c.get("value") or "").strip()
    return ""

# Thu thập tất cả mã Shopee từ cột A (bỏ header + placeholder)
shopee_codes = set()
r = 2
while True:
    code = cell_val("A", r)
    if not code:
        blank = sum(1 for i in range(5) if not cell_val("A", r + i))
        if blank >= 5:
            break
        r += 1
        continue
    if code not in ("product_shopee",):
        shopee_codes.add(code)
    r += 1

print(f"[INFO] Spreadsheet có {len(shopee_codes)} mã Shopee")

# ── 2. Map shopee code → sale.order IDs ────────────────────────────────────
SaleOrder = env["sale.order"].sudo()
valid_so_ids = set()
not_found_codes = []

for code in shopee_codes:
    so = SaleOrder.search([("x_studio_tham_chiu_shopee", "=", code)], limit=1, order="id desc")
    if so:
        valid_so_ids.add(so.id)
    else:
        not_found_codes.append(code)

print(f"[INFO] Map được {len(valid_so_ids)} sale.order tương ứng")
if not_found_codes:
    print(f"[WARN] {len(not_found_codes)} mã Shopee không tìm thấy SO (bỏ qua): {not_found_codes[:5]}...")

# ── 3. Tìm HDDT nháp KHÔNG trong danh sách ──────────────────────────────────
print()
print("=" * 70)
print("Tìm meinvoice.invoice Nháp KHÔNG trong spreadsheet")
print("=" * 70)

Invoice = env["meinvoice.invoice"].sudo()

# Lấy tất cả draft invoice
all_draft = Invoice.search([("state", "=", "draft")])
print(f"[INFO] Tổng HDDT nháp trong DB: {len(all_draft)}")

# Lọc ra những cái KHÔNG thuộc sale order trong spreadsheet
to_cancel = all_draft.filtered(lambda inv: inv.sale_order_id.id not in valid_so_ids)
in_sheet  = all_draft - to_cancel

print(f"[INFO] HDDT nháp thuộc spreadsheet     : {len(in_sheet)}")
print(f"[INFO] HDDT nháp KHÔNG trong spreadsheet: {len(to_cancel)}  <- sẽ hủy")

# ── 4. In danh sách sẽ hủy ──────────────────────────────────────────────────
print()
print("=" * 70)
mode_label = "[DRY RUN]" if DRY_RUN else "[LIVE CANCEL]"
print(f"{mode_label}")
print("=" * 70)

if not to_cancel:
    print("  Không có HDDT nháp nào cần hủy.")
else:
    print(f"  {'ID':>6} | {'Đơn hàng':<12} | {'Khách hàng':<30} | {'Ký hiệu':<12} | Ngày HĐ")
    print(f"  {'-'*6}-+-{'-'*12}-+-{'-'*30}-+-{'-'*12}-+-{'-'*10}")
    for inv in to_cancel:
        so_name   = inv.sale_order_id.name if inv.sale_order_id else "(Không có SO)"
        partner   = (inv.partner_id.name or "")[:30]
        inv_series = inv.inv_series or ""
        inv_date  = str(inv.inv_date) if inv.inv_date else ""
        print(f"  {inv.id:>6} | {so_name:<12} | {partner:<30} | {inv_series:<12} | {inv_date}")

# ── 5. Thực hiện hủy ─────────────────────────────────────────────────────────
print()
cancelled = 0
errors    = []

if not DRY_RUN and to_cancel:
    for inv in to_cancel:
        try:
            inv.action_cancel()
            cancelled += 1
        except Exception as e:
            errors.append((inv.id, inv.sale_order_id.name, str(e)))
            print(f"  [ERROR] id={inv.id} SO={inv.sale_order_id.name}: {e}")

    env.cr.commit()
    print(f"[SUCCESS] Đã hủy {cancelled} HDDT và commit.")
elif DRY_RUN:
    cancelled = len(to_cancel)

# ── 6. Summary ───────────────────────────────────────────────────────────────
print()
print("=" * 70)
print(f"KẾT QUẢ {mode_label}")
print(f"  Tổng HDDT nháp trong DB         : {len(all_draft)}")
print(f"  Thuộc đơn trong spreadsheet     : {len(in_sheet)} (giữ nguyên)")
print(f"  Sẽ/đã hủy                       : {cancelled}")
print(f"  Lỗi                             : {len(errors)}")
for iid, so_name, msg in errors:
    print(f"    - id={iid} SO={so_name}: {msg}")
if DRY_RUN:
    print("\n[DRY RUN] Chưa hủy gì. Đặt DRY_RUN=False để chạy thật.")
print("=" * 70)
