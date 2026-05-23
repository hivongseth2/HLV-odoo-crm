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

import json, base64, zlib, re as _re

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

# ── Apply revisions để đọc dữ liệu mới nhất (không dùng cache snapshot) ──────
def _col_letter(idx):
    result = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        result = chr(65 + r) + result
    return result

def _parse_cell_key(key):
    m = _re.match(r'^([A-Z]+)(\d+)$', key)
    if not m:
        return None, None
    col0 = 0
    for ch in m.group(1):
        col0 = col0 * 26 + (ord(ch) - ord('A') + 1)
    return col0 - 1, int(m.group(2)) - 1

def _apply_revisions_to_cells(cells_dict, all_cmds):
    internal = {}
    for key, val in cells_dict.items():
        c, r = _parse_cell_key(key)
        if c is None:
            continue
        content = (val.get("content") or val.get("value") or "") if isinstance(val, dict) else str(val)
        if content:
            internal[(c, r)] = str(content)
    for cmd in all_cmds:
        ctype = cmd.get("type", "")
        if ctype == "UPDATE_CELL":
            if "col" not in cmd or "row" not in cmd:
                continue
            c, r = cmd["col"], cmd["row"]
            content = cmd.get("content", "")
            if content:
                internal[(c, r)] = content
            else:
                internal.pop((c, r), None)
        elif ctype == "CLEAR_CELL":
            if "col" not in cmd or "row" not in cmd:
                continue
            internal.pop((cmd["col"], cmd["row"]), None)
        elif ctype == "DELETE_CONTENT":
            # Dạng range: target = [{left, right, top, bottom}]
            if "target" in cmd:
                for zone in cmd.get("target", []):
                    for rr in range(zone["top"], zone["bottom"] + 1):
                        for cc in range(zone["left"], zone["right"] + 1):
                            internal.pop((cc, rr), None)
            elif "col" in cmd and "row" in cmd:
                internal.pop((cmd["col"], cmd["row"]), None)
        elif ctype == "ADD_COLUMNS_ROWS" and cmd.get("dimension") == "ROW":
            base      = cmd.get("base", 0)
            quantity  = cmd.get("quantity", 1)
            position  = cmd.get("position", "after")
            insert_at = base + 1 if position == "after" else base
            internal  = {
                (c, r + quantity if r >= insert_at else r): v
                for (c, r), v in internal.items()
            }
        elif ctype == "REMOVE_COLUMNS_ROWS" and cmd.get("dimension") == "ROW":
            remove_set = set(cmd.get("elements", []))
            survivors  = {(c, r): v for (c, r), v in internal.items() if r not in remove_set}
            sorted_removed = sorted(remove_set)
            internal = {
                (c, r - sum(1 for x in sorted_removed if x < r)): v
                for (c, r), v in survivors.items()
            }
    return {
        _col_letter(c) + str(r + 1): {"content": v}
        for (c, r), v in internal.items()
    }

_revisions = doc.sudo().spreadsheet_revision_ids
print(f"[INFO] Tổng revision chờ apply: {len(_revisions)}")
_cmds_by_sheet = {}
for _rev in _revisions.sorted("id"):
    _raw = getattr(_rev, "commands", "") or ""
    try:
        _msg = json.loads(_raw)
    except Exception:
        continue
    _cmds = _msg if isinstance(_msg, list) else _msg.get("commands", [])
    for _cmd in _cmds:
        _sid = _cmd.get("sheetId", "")
        _cmds_by_sheet.setdefault(_sid, []).append(_cmd)
for _sh in data.get("sheets", []):
    _sid  = _sh.get("id", "")
    _cmds = _cmds_by_sheet.get(_sid, [])
    if _cmds:
        _sh["cells"] = _apply_revisions_to_cells(_sh.get("cells", {}), _cmds)
print("[INFO] Đã apply xong revisions — dữ liệu đọc là mới nhất.")
# ─────────────────────────────────────────────────────────────────────────────

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

# ── 3b. Đơn trong spreadsheet KHÔNG có HDDT nháp ────────────────────────────
so_ids_have_draft = set(in_sheet.mapped("sale_order_id").ids)
so_ids_no_draft   = valid_so_ids - so_ids_have_draft
print()
print("=" * 70)
print(f"Đơn trong spreadsheet KHÔNG có HDDT nháp: {len(so_ids_no_draft)}")
print("=" * 70)
if so_ids_no_draft:
    sos_no_draft = SaleOrder.browse(list(so_ids_no_draft))
    print(f"  {'ID':>7} | {'Mã đơn':<12} | {'Khách hàng':<30} | Mã Shopee")
    print(f"  {'-'*7}-+-{'-'*12}-+-{'-'*30}-+-{'-'*20}")
    for so in sos_no_draft.sorted("name"):
        partner = (so.partner_id.name or "")[:30]
        shopee  = so.x_studio_tham_chiu_shopee or ""
        print(f"  {so.id:>7} | {so.name:<12} | {partner:<30} | {shopee}")
else:
    print("  (Tất cả đơn trong spreadsheet đều đã có HDDT nháp)")

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
