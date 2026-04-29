#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Odoo shell script - tra ID danh mục MISA cho phiếu nhập kho theo picking/PO.

Chạy:
    odoo-bin shell -c <odoo.conf> --no-http < bin/get_misa_dictionary_ids_for_inward.py
"""

PICKING_NAME = "KBC/IN/09169"
PO_NAME = "DMH18228"
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

# 1) Branch (data_type=2): lấy page đầu để xem branch khả dụng
branches = cfg.get_dictionary(data_type=2, take=100).get("items") or []
print("\n[Branch - data_type=2]")
if branches:
    for b in branches[:10]:
        print("-", b.get("branch_id"), "|", b.get("branch_name"), "|", b.get("branch_code"))
else:
    print("- Không có dữ liệu branch hoặc tài khoản không được quyền xem")

# 2) Stock (data_type=5)
stock_item = cfg.find_dictionary_item_by_code(
    data_type=5,
    code_field="stock_code",
    code_value=STOCK_CODE,
    branch_id=None,
)
print("\n[Stock - data_type=5]")
if stock_item:
    print("- stock_id   :", stock_item.get("stock_id"))
    print("- stock_code :", stock_item.get("stock_code"))
    print("- stock_name :", stock_item.get("stock_name"))
    print("- branch_id  :", stock_item.get("branch_id"))
else:
    print("- Không tìm thấy kho theo stock_code =", STOCK_CODE)

# 3) Account object (data_type=1)
acc_item = cfg.find_dictionary_item_by_code(
    data_type=1,
    code_field="account_object_code",
    code_value=partner_code,
    branch_id=None,
)
print("\n[Account Object - data_type=1]")
if acc_item:
    print("- account_object_id   :", acc_item.get("account_object_id"))
    print("- account_object_code :", acc_item.get("account_object_code"))
    print("- account_object_name :", acc_item.get("account_object_name"))
else:
    print("- Không tìm thấy account object theo code =", partner_code)

# 4) Product + UoM cho từng dòng picking
print("\n[Products/UoM]")
for mv in picking.move_ids_without_package.filtered(lambda m: m.quantity > 0):
    code = (mv.product_id.default_code or "").strip()
    uom_name = (mv.product_uom.name or "").strip()

    prod_item = cfg.find_dictionary_item_by_code(
        data_type=3,
        code_field="inventory_item_code",
        code_value=code,
        branch_id=None,
    ) if code else False

    unit_item = cfg.find_dictionary_item_by_code(
        data_type=6,
        code_field="unit_name",
        code_value=uom_name,
        branch_id=None,
    ) if uom_name else False

    print("-", mv.product_id.display_name)
    print("    inventory_item_code:", code)
    print("    inventory_item_id  :", prod_item.get("inventory_item_id") if prod_item else "(không tìm thấy)")
    print("    unit_name          :", uom_name)
    print("    unit_id            :", unit_item.get("unit_id") if unit_item else "(không tìm thấy)")

print("\nHoàn tất. Dùng các ID trên để build payload có link chuẩn.")
