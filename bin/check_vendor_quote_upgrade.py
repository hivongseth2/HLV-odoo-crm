# -*- coding: utf-8 -*-
"""
check_vendor_quote_upgrade.py
=============================
Kiểm dữ liệu "Hỏi giá NCC" khi upgrade hlv_vendor_quotation trên prd (18.0.3.44.0 → 18.0.3.56.0):
migration 3.47 / 3.49 sửa đúng chỗ, và KHÔNG đụng tiền / số lượng của báo giá, YCMH, đơn mua.

CHỈ ĐỌC DATABASE — không write / create / unlink. Thứ duy nhất script ghi là một file JSON (ảnh chụp).

Cách dùng — chạy 2 lần trong odoo-bin shell của prd (Odoo.sh → Shell):
  1) TRƯỚC khi đẩy code mới (đang 3.44): dán TOÀN BỘ file này vào `odoo-bin shell` (hoặc
     `odoo-bin shell -d <DB> < check_vendor_quote_upgrade.py`). Chưa có file ảnh chụp → chụp + lưu.
  2) SAU khi upgrade xong (3.56): chạy lại y như vậy. Đã có file ảnh chụp → chụp lại + so sánh + kiểm.
  Muốn chụp lại từ đầu: đặt MODE = "before" bên dưới (ghi đè file cũ).

File ảnh chụp: SNAPSHOT (mặc định /home/odoo/data/... — thư mục data của Odoo.sh giữ qua các lần build;
/tmp mất khi build lại).

Đọc gì: mọi phiếu hỏi giá / dòng / báo giá / dòng báo giá / link NCC; YCMH lên từ trang hỏi giá hoặc có dòng
nối với báo giá; dòng YCMH của các YCMH đó; dòng đơn mua nối với dòng YCMH (+ đơn mua); phiếu kho (stock.move)
của các dòng đơn mua. Đọc bằng SQL theo cột thực có của bảng → chạy được trên cả schema cũ lẫn mới.

So sánh (chỉ cột có ở cả hai lần chụp; bỏ write_date / write_uid):
  - Đổi CÓ CHỦ ĐÍCH (migration được phép đổi) — kiểm giá trị mới có đúng không:
      dòng phiếu need_qty, dòng báo giá chosen_qty / request_line_id, phiếu sale_status, link NCC short_code,
      dòng YCMH: bộ cột "sale đề xuất" (sale_proposed_*, misa_*) — CHỈ ở dòng trước đó còn trống.
  - Đổi NGOÀI DỰ KIẾN — in ra hết; cột tiền / số lượng (price, amount, qty, total, cost, tax, discount)
    gắn [TIỀN/SL] — đây là thứ phải bằng 0.
Kiểm bất biến sau upgrade: NCC đang chọn có SL mua > 0 và ≤ SL hỏi; SL cần mua > 0, ≤ SL hỏi, đã lên YCMH thì
= tổng SL mua; dòng báo giá ↔ dòng YCMH cùng sản phẩm + cùng NCC; giá "sale đề xuất" vừa điền = giá NCC báo;
link NCC có mã ngắn, không trùng. Cuối cùng so TỔNG TIỀN trước / sau.
"""

MODE = "auto"   # "auto": chưa có file → before, có file → after.  "before" / "after": ép.
SNAPSHOT = "/home/odoo/data/vq_upgrade_before.json"
SHOW_LIMIT = 40  # mỗi nhóm in tối đa chừng này dòng chi tiết

# Bọc trong exec: dán vào REPL của odoo-bin shell không bị vỡ bởi dòng trống trong hàm / vòng lặp.
SOURCE = r'''
import json
import os
from datetime import date, datetime
from decimal import Decimal

cr = env.cr
MONEY_QTY = ("price", "amount", "qty", "total", "cost", "tax", "discount", "subtotal", "quantity")
IGNORED = {"write_date", "write_uid", "__last_update"}  # chụp lại nhưng không so
MIGRATION_UID = 1  # migration chạy bằng superuser — sửa bởi uid khác là người dùng thao tác giữa hai lần chụp
# Cột migration được phép đổi (bảng → cột). Dòng YCMH: chỉ khi trước đó bộ "sale đề xuất" còn trống.
EXPECTED = {
    "hlv_vendor_inquiry_line": {"need_qty"},
    "hlv_vendor_quote_line": {"chosen_qty", "request_line_id"},
    "hlv_vendor_inquiry": {"sale_status"},
    "hlv_vendor_quote_access": {"short_code"},
}
PROPOSAL_PREFIX = ("sale_proposed_", "misa_")


def columns(table):
    cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position", [table])
    return [r[0] for r in cr.fetchall()]


def jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, memoryview)):
        return None
    if isinstance(v, dict):
        return v
    return v


def dump(table, where="", params=()):
    cols = [c for c in columns(table) if c != "__last_update"]
    if not cols:
        return {}
    cr.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}" {where}', params)
    return {str(row[0]): {c: jsonable(v) for c, v in zip(cols, row)} for row in cr.fetchall()} if cols[0] == "id" else {}


def ids_of(rows):
    return [int(i) for i in rows]


def snapshot():
    snap = {"taken_at": datetime.now().isoformat(timespec="seconds")}
    cr.execute("SELECT latest_version FROM ir_module_module WHERE name = 'hlv_vendor_quotation'")
    snap["module_version"] = (cr.fetchone() or [None])[0]
    for t in ("hlv_vendor_inquiry", "hlv_vendor_inquiry_line", "hlv_vendor_quote", "hlv_vendor_quote_line",
              "hlv_vendor_quote_access"):
        snap[t] = dump(t)
    # YCMH liên quan: lên từ trang hỏi giá, hoặc có dòng nối với dòng báo giá / dòng phiếu (cột cũ request_line_id).
    req_line_ids = set()
    for t, col in (("hlv_vendor_quote_line", "request_line_id"), ("hlv_vendor_quote_line", "backorder_request_line_id"),
                   ("hlv_vendor_inquiry_line", "request_line_id")):
        for row in snap[t].values():
            if row.get(col):
                req_line_ids.add(row[col])
    req_ids = set()
    if req_line_ids:
        cr.execute("SELECT DISTINCT request_id FROM purchase_request_line WHERE id = ANY(%s)", [list(req_line_ids)])
        req_ids |= {r[0] for r in cr.fetchall()}
    if "hlv_from_quote_page" in columns("purchase_request"):
        cr.execute("SELECT id FROM purchase_request WHERE hlv_from_quote_page")
        req_ids |= {r[0] for r in cr.fetchall()}
    for row in snap["hlv_vendor_quote"].values():
        if row.get("request_id"):
            req_ids.add(row["request_id"])
    req_ids = sorted(req_ids)
    snap["purchase_request"] = dump("purchase_request", "WHERE id = ANY(%s)", [req_ids]) if req_ids else {}
    snap["purchase_request_line"] = dump("purchase_request_line", "WHERE request_id = ANY(%s)", [req_ids]) if req_ids else {}
    prl = ids_of(snap["purchase_request_line"])
    pol_ids = []
    if prl:
        cr.execute("SELECT DISTINCT purchase_order_line_id FROM purchase_request_purchase_order_line_rel "
                   "WHERE purchase_request_line_id = ANY(%s)", [prl])
        pol_ids = sorted(r[0] for r in cr.fetchall())
        cr.execute("SELECT purchase_request_line_id, purchase_order_line_id FROM purchase_request_purchase_order_line_rel "
                   "WHERE purchase_request_line_id = ANY(%s)", [prl])
        snap["pr_po_rel"] = sorted([list(r) for r in cr.fetchall()])
    else:
        snap["pr_po_rel"] = []
    snap["purchase_order_line"] = dump("purchase_order_line", "WHERE id = ANY(%s)", [pol_ids]) if pol_ids else {}
    po_ids = sorted({r["order_id"] for r in snap["purchase_order_line"].values()})
    snap["purchase_order"] = dump("purchase_order", "WHERE id = ANY(%s)", [po_ids]) if po_ids else {}
    snap["stock_move"] = dump("stock_move", "WHERE purchase_line_id = ANY(%s)", [pol_ids]) if pol_ids else {}
    return snap


def num(v):
    return float(v or 0.0)


def money_totals(s):
    """Tổng tiền / SL chính để so trước-sau (sau VAT theo % thuế lưu trên dòng báo giá)."""
    q = sum(num(r.get("price_unit")) * num(r.get("product_qty")) * (1 + num(r.get("tax_rate")) / 100)
            for r in s["hlv_vendor_quote_line"].values() if not r.get("unavailable"))
    return {
        "Báo giá NCC: Σ đơn giá × SL hỏi (sau VAT)": round(q, 2),
        "Báo giá NCC: Σ SL hỏi": round(sum(num(r.get("product_qty")) for r in s["hlv_vendor_quote_line"].values()), 4),
        "Phiếu: Σ SL hỏi": round(sum(num(r.get("product_qty")) for r in s["hlv_vendor_inquiry_line"].values()), 4),
        "YCMH: Σ SL": round(sum(num(r.get("product_qty")) for r in s["purchase_request_line"].values()), 4),
        "YCMH: Σ SL thực mua × giá thực mua": round(sum(num(r.get("actual_qty")) * num(r.get("actual_price_unit"))
                                                        for r in s["purchase_request_line"].values()), 2),
        "Đơn mua: Σ tổng tiền (amount_total)": round(sum(num(r.get("amount_total")) for r in s["purchase_order"].values()), 2),
        "Dòng đơn mua: Σ SL": round(sum(num(r.get("product_qty")) for r in s["purchase_order_line"].values()), 4),
        "Dòng đơn mua: Σ thành tiền (price_subtotal)": round(sum(num(r.get("price_subtotal")) for r in s["purchase_order_line"].values()), 2),
        "Phiếu kho: Σ SL (product_uom_qty)": round(sum(num(r.get("product_uom_qty")) for r in s["stock_move"].values()), 4),
    }


def same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))
    return a == b


def is_money(col):
    return any(k in col for k in MONEY_QTY)


def compare(before, after):
    unexpected, expected = [], []
    for table, rows_b in before.items():
        if not isinstance(rows_b, dict) or table in ("taken_at",):
            continue
        rows_a = after.get(table, {})
        gone = sorted(set(rows_b) - set(rows_a), key=int)
        if gone:
            unexpected.append((table, "MẤT BẢN GHI", ", ".join(gone[:20]) + (" …" if len(gone) > 20 else ""), True))
        for rid, rb in rows_b.items():
            ra = rows_a.get(rid)
            if not ra:
                continue
            proposal_was_empty = table == "purchase_request_line" and not rb.get("sale_proposed_supplier_id") \
                and not num(rb.get("misa_price_before_tax"))
            by_user = ra.get("write_uid") not in (None, MIGRATION_UID) and ra.get("write_date") != rb.get("write_date")
            note = f"   (sửa bởi user {ra.get('write_uid')} lúc {ra.get('write_date')} — người dùng thao tác, không phải migration?)" if by_user else ""
            for col, vb in rb.items():
                if col in IGNORED or col not in ra or same(vb, ra[col]):
                    continue
                ok = col in EXPECTED.get(table, set()) or (proposal_was_empty and col.startswith(PROPOSAL_PREFIX))
                (expected if ok else unexpected).append((table, f"id {rid} · {col}", f"{vb!r} → {ra[col]!r}{note}", is_money(col)))
    gone = sorted(set(map(tuple, before.get("pr_po_rel", []))) - set(map(tuple, after.get("pr_po_rel", []))))
    if gone:
        unexpected.append(("purchase_request_purchase_order_line_rel", "MẤT LIÊN KẾT dòng YCMH ↔ dòng đơn mua", str(gone[:20]), True))
    return unexpected, expected


def invariants(s):
    """Kiểm sau upgrade trên ảnh chụp mới. Trả [(tên kiểm, [lỗi])]."""
    inq_lines, qlines = s["hlv_vendor_inquiry_line"], s["hlv_vendor_quote_line"]
    prl, quotes = s["purchase_request_line"], s["hlv_vendor_quote"]
    res = []
    if not any("chosen_qty" in r for r in qlines.values()):
        return [("Schema mới (chosen_qty / need_qty)", ["chưa có cột mới — chưa upgrade?"])]
    errs = []
    for rid, r in qlines.items():
        if r.get("selected") and r.get("inquiry_line_id"):
            asked = num(inq_lines.get(str(r["inquiry_line_id"]), {}).get("product_qty"))
            if not (num(r.get("chosen_qty")) > 0):
                errs.append(f"dòng báo giá {rid}: đang chọn mà SL mua = {r.get('chosen_qty')}")
            elif num(r.get("chosen_qty")) > asked + 1e-6:
                errs.append(f"dòng báo giá {rid}: SL mua {r.get('chosen_qty')} > SL hỏi {asked}")
    res.append(("NCC đang chọn: 0 < SL mua ≤ SL hỏi", errs))
    errs = []
    chosen_by_line = {}
    has_request = set()
    rejected = {k for k, v in s["purchase_request"].items() if v.get("state") == "rejected"}
    live = {k for k, v in prl.items() if not v.get("cancelled") and str(v.get("request_id")) not in rejected}
    for r in qlines.values():
        if r.get("selected") and r.get("inquiry_line_id"):
            chosen_by_line[r["inquiry_line_id"]] = chosen_by_line.get(r["inquiry_line_id"], 0.0) + num(r.get("chosen_qty"))
            if str(r.get("request_line_id") or "") in live:
                has_request.add(r["inquiry_line_id"])
    for rid, r in inq_lines.items():
        need, asked = num(r.get("need_qty")), num(r.get("product_qty"))
        if need <= 0:
            errs.append(f"dòng phiếu {rid}: SL cần mua = {r.get('need_qty')}")
        elif need > asked + 1e-6:
            errs.append(f"dòng phiếu {rid}: SL cần mua {need} > SL hỏi {asked}")
        if int(rid) in has_request and abs(need - chosen_by_line.get(int(rid), 0.0)) > 1e-6:
            errs.append(f"dòng phiếu {rid}: đã lên YCMH, SL cần mua {need} ≠ tổng SL mua {chosen_by_line.get(int(rid))}")
    res.append(("SL cần mua: > 0, ≤ SL hỏi; đã lên YCMH thì = tổng SL mua", errs))
    errs, warns = [], []
    cr.execute("SELECT id, commercial_partner_id FROM res_partner")
    commercial = dict(cr.fetchall())
    for rid, r in qlines.items():
        for col in ("request_line_id", "backorder_request_line_id"):
            pid = r.get(col)
            if not pid:
                continue
            p = prl.get(str(pid))
            if not p:
                errs.append(f"dòng báo giá {rid}: {col}={pid} không thuộc YCMH đã chụp")
                continue
            if p.get("product_id") != r.get("product_id"):
                errs.append(f"dòng báo giá {rid}: {col}={pid} khác sản phẩm ({r.get('product_id')} ≠ {p.get('product_id')})")
            vendor_q = commercial.get(quotes.get(str(r.get("quote_id")), {}).get("partner_id"))
            vendor_p = commercial.get(p.get("actual_supplier_id")) if p.get("actual_supplier_id") else None
            if vendor_p and vendor_q and vendor_p != vendor_q and not p.get("cancelled"):
                warns.append(f"dòng báo giá {rid}: {col}={pid} khác NCC (báo giá {vendor_q} ≠ NCC thực mua {vendor_p})")
    res.append(("Dòng báo giá ↔ dòng YCMH: cùng sản phẩm", errs))
    res.append(("(Cảnh báo, xem tay) Dòng báo giá ↔ dòng YCMH khác NCC — thu mua có thể đã đổi NCC khi Tạo RFQ", warns))
    errs = []
    cr.execute("SELECT short_code, count(*) FROM hlv_vendor_quote_access GROUP BY short_code HAVING short_code IS NULL OR count(*) > 1")
    for code, n in cr.fetchall():
        errs.append(f"mã ngắn {code!r}: {n} link")
    res.append(("Link NCC: có mã ngắn, không trùng", errs))
    return res


def check_proposals(before, after):
    """Dòng YCMH vừa được điền "sale đề xuất": giá / thuế / NCC phải khớp dòng báo giá đang chọn trỏ tới nó."""
    errs, filled = [], 0
    by_req = {}
    for r in after["hlv_vendor_quote_line"].values():
        if r.get("selected") and r.get("request_line_id"):
            by_req[str(r["request_line_id"])] = r
    quotes = after["hlv_vendor_quote"]
    for rid, ra in after["purchase_request_line"].items():
        rb = before["purchase_request_line"].get(rid)
        if not rb or rb.get("sale_proposed_supplier_id") or num(rb.get("misa_price_before_tax")):
            continue
        if not ra.get("sale_proposed_supplier_id"):
            continue
        filled += 1
        q = by_req.get(rid)
        if not q:
            errs.append(f"dòng YCMH {rid}: được điền mà không có dòng báo giá đang chọn trỏ tới")
            continue
        if abs(num(ra.get("misa_price_before_tax")) - num(q.get("price_unit"))) > 0.01:
            errs.append(f"dòng YCMH {rid}: giá trước thuế {ra.get('misa_price_before_tax')} ≠ giá NCC {q.get('price_unit')}")
        if abs(num(ra.get("misa_tax_rate")) - num(q.get("tax_rate"))) > 1e-6:
            errs.append(f"dòng YCMH {rid}: % thuế {ra.get('misa_tax_rate')} ≠ {q.get('tax_rate')}")
        if ra.get("sale_proposed_supplier_id") != quotes.get(str(q.get("quote_id")), {}).get("partner_id"):
            errs.append(f"dòng YCMH {rid}: NCC đề xuất {ra.get('sale_proposed_supplier_id')} ≠ NCC báo giá")
    return filled, errs


def show(title, items, limit=SHOW_LIMIT):
    print(f"\n=== {title}: {len(items)}")
    for it in items[:limit]:
        print("   ", it)
    if len(items) > limit:
        print(f"    … còn {len(items) - limit}")


mode = MODE
if mode == "auto":
    mode = "after" if os.path.exists(SNAPSHOT) else "before"
now = snapshot()
counts = {t: len(v) for t, v in now.items() if isinstance(v, dict)}
print(f"\nhlv_vendor_quotation {now['module_version']} — chụp lúc {now['taken_at']} — chế độ {mode.upper()}")
print("Số bản ghi:", json.dumps(counts, ensure_ascii=False))
if mode == "before":
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    with open(SNAPSHOT, "w", encoding="utf-8") as fh:
        json.dump(now, fh, ensure_ascii=False, default=str)
    print(f"\nĐÃ LƯU ảnh chụp TRƯỚC upgrade: {SNAPSHOT} ({os.path.getsize(SNAPSHOT)} byte)")
    for k, v in money_totals(now).items():
        print(f"   {k}: {v:,}")
else:
    with open(SNAPSHOT, encoding="utf-8") as fh:
        before = json.load(fh)
    print(f"So với ảnh chụp {before['taken_at']} (version {before['module_version']})")
    cb = {t: len(v) for t, v in before.items() if isinstance(v, dict)}
    for t in sorted(set(cb) | set(counts)):
        if cb.get(t) != counts.get(t):
            print(f"   ! số bản ghi {t}: {cb.get(t)} → {counts.get(t)}")
    unexpected, expected = compare(before, now)
    money = [f"[TIỀN/SL] {t} · {k}: {v}" for t, k, v, m in unexpected if m]
    other = [f"{t} · {k}: {v}" for t, k, v, m in unexpected if not m]
    show("ĐỔI NGOÀI DỰ KIẾN — TIỀN / SỐ LƯỢNG (phải = 0)", money)
    show("Đổi ngoài dự kiến — cột khác", other)
    show("Đổi có chủ đích (migration)", [f"{t} · {k}: {v}" for t, k, v, m in expected], limit=15)
    filled, perr = check_proposals(before, now)
    print(f"\n=== Dòng YCMH được điền bù 'sale đề xuất': {filled}")
    show("  lệch với giá NCC đã chọn", perr)
    for name, errs in invariants(now):
        show(("OK   " if not errs else "LỖI  ") + name, errs)
    print("\n=== Tổng tiền / số lượng (trước → sau)")
    tb, ta = money_totals(before), money_totals(now)
    for k in tb:
        flag = "" if same(tb[k], ta[k]) else "   <<< KHÁC"
        print(f"   {k}: {tb[k]:,} → {ta[k]:,}{flag}")
    verdict = "KHÔNG có thay đổi tiền / SL ngoài dự kiến" if not money else f"CÓ {len(money)} thay đổi tiền / SL ngoài dự kiến — xem trên"
    print(f"\nKẾT LUẬN: {verdict}.")
'''
exec(SOURCE, dict(globals(), MODE=MODE, SNAPSHOT=SNAPSHOT, SHOW_LIMIT=SHOW_LIMIT))
