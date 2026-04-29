#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Odoo shell script - tra ID danh mục MISA cho phiếu nhập kho theo picking/PO.

Chạy:
    odoo-bin shell -c <odoo.conf> --no-http < bin/get_misa_dictionary_ids_for_inward.py
"""

PICKING_NAME = "KBC/IN/09189"
PO_NAME = "DMH18241"
STOCK_CODE = "HLV"

cfg = env["amis.callback.config"].sudo().ensure_singleton()
cfg.ensure_sync_ready()

picking = env["stock.picking"].sudo().search([("name", "=", PICKING_NAME)], limit=1)
if not picking:
    raise Exception("Không tìm thấy phiếu: %s" % PICKING_NAME)

po = env["purchase.order"].sudo().search([("name", "=", PO_NAME)], limit=1)
if not po and picking.origin:
    po = env["purchase.order"].sudo().search([("name", "=", picking.origin)], limit=1)

partner = picking.partner_id or (po.partner_id if po else env["res.partner"])
partner_code = (partner.ref or partner.name or "").strip() if partner else ""

print("=" * 70)
print("Tra MISA dictionary cho:")
print("- Picking      :", picking.name)
print("- Purchase     :", po.name if po else "(không tìm thấy)")
print("- Partner code :", partner_code)
print("- Stock code   :", STOCK_CODE)
print("=" * 70)

import json as _json

# data_type đúng theo tài liệu MISA ACT OpenAPI:
# 1=Đối tượng, 2=Vật tư, 3=Kho, 4=Đơn vị tính
DT_ACCOUNT_OBJECT = 1
DT_INVENTORY_ITEM = 2
DT_STOCK         = 3
DT_UNIT          = 4

# ── Kho (data_type=3) ─────────────────────────────────────────────────────────
print("\n[Kho - data_type=3]")
st_result = cfg.get_dictionary(data_type=DT_STOCK, take=100)
stocks = st_result.get("items") or []
print(f"  {len(stocks)} kho tìm thấy")
for s in stocks:
    print(" -", repr(s.get("stock_code")), "|", s.get("stock_name"), "| stock_id:", s.get("stock_id"), "| branch_id:", s.get("branch_id"))
if stocks:
    print("  (raw 1st item):", _json.dumps(stocks[0], ensure_ascii=False)[:400])

# ── Đơn vị tính (data_type=4) ─────────────────────────────────────────────────
print("\n[Đơn vị tính - data_type=4]")
unit_result = cfg.get_dictionary(data_type=DT_UNIT, take=100)
units = unit_result.get("items") or []
print(f"  {len(units)} đơn vị")
for u in units[:30]:
    print(" -", repr(u.get("unit_name")), "| unit_id:", u.get("unit_id"))

# ── Vật tư (data_type=2) - tìm code 7447 ──────────────────────────────────────
print("\n[Vật tư - data_type=2] tìm code='7447'")
found_prod = None
skip = 0
while not found_prod:
    r = cfg.get_dictionary(data_type=DT_INVENTORY_ITEM, skip=skip, take=100)
    items = r.get("items") or []
    if not items:
        break
    for p in items:
        if (p.get("inventory_item_code") or "").strip() == "7447":
            found_prod = p
            break
    if found_prod or len(items) < 100:
        break
    skip += 100

if found_prod:
    print("  inventory_item_id:", found_prod.get("inventory_item_id"))
    print("  unit_id          :", found_prod.get("unit_id"))
    print("  raw:", _json.dumps(found_prod, ensure_ascii=False)[:300])
else:
    print("  Không tìm thấy code=7447")
    r0 = cfg.get_dictionary(data_type=DT_INVENTORY_ITEM, take=3)
    print("  Mẫu:", [(p.get("inventory_item_code"), p.get("inventory_item_name")) for p in r0.get("items") or []])

# ── Đối tượng (data_type=1) - tìm DAVITA ──────────────────────────────────────
print("\n[Đối tượng - data_type=1] tìm DAVITA")
found_acc = None
skip = 0
while not found_acc:
    r = cfg.get_dictionary(data_type=DT_ACCOUNT_OBJECT, skip=skip, take=100)
    items = r.get("items") or []
    if not items:
        break
    for a in items:
        aname = (a.get("account_object_name") or "").upper()
        acode = (a.get("account_object_code") or "").upper()
        if "DAVITA" in aname or "DAVITA" in acode:
            found_acc = a
            break
    if found_acc or len(items) < 100:
        break
    skip += 100

if found_acc:
    print("  account_object_id  :", found_acc.get("account_object_id"))
    print("  account_object_code:", found_acc.get("account_object_code"))
    print("  account_object_name:", found_acc.get("account_object_name"))
else:
    print("  Không tìm thấy DAVITA - thử với VAT/mã số thuế của partner:")
    print("  - partner.vat:", partner.vat if partner else "N/A")
    print("  - partner.ref:", partner.ref if partner else "N/A")

print("\nHoàn tất.")
