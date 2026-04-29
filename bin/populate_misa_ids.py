#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Odoo shell script - điền sẵn MISA IDs vào res.partner, product.product, uom.uom.

IDs lấy từ get_misa_dictionary_ids_for_inward.py.
Chạy 1 lần; có thể chạy lại an toàn (idempotent).

Cách chạy:
    odoo-bin shell -c <odoo.conf> --no-http < bin/populate_misa_ids.py
"""

# ─── CONFIG: điền IDs tìm được ───────────────────────────────────────────────

# Đơn vị tính
UNIT_MAP = {
    # odoo_uom_name : misa_unit_id
    'Cái':     '71112249-98ce-4334-a06d-34736155fa35',
    'CÁI':     '6be8b2a1-1731-4673-9fca-b9053151aeef',
    'Bộ':      '39e7c3d8-ca57-400d-9ebc-bf6a48717b7c',
    'Chiếc':   '3a3d4460-f54b-46b5-a26a-cd416a020fa7',
    'Hộp':     None,   # Chưa tìm được - điền thêm nếu cần
    'Cuộn':    '2117bfeb-a14b-4910-890e-6027d30e4a3f',
    'Kg':      None,   # Điền thêm
    'M':       None,
    'Chai':    '81cebf94-9cb9-4b20-880a-a01fc0f6d850',
    'Bao':     '31597062-7d39-4b6d-bc65-6fde28dc71f7',
}

# Partner (NCC/KH)
PARTNER_MAP = {
    # partner_name_or_ref : (misa_account_object_id, account_object_code)
    'CÔNG TY CỔ PHẦN KỸ THUẬT DAVITA (Đất Việt)': (
        'c7fa9f7a-8362-469e-a487-108890f6b41d', 'DAVITA'
    ),
    # Thêm các partner khác tại đây:
    # 'TÊN PARTNER': ('misa-uuid', 'misa-code'),
}

# Sản phẩm
PRODUCT_MAP = {
    # default_code : (misa_inventory_item_id, misa_unit_id)
    '7447': (
        '088ee242-10a9-43b7-8d4f-c60afc8f5f8d',
        '71112249-98ce-4334-a06d-34736155fa35',
    ),
    # Thêm các sản phẩm khác tại đây:
    # 'PRODUCT_CODE': ('misa-item-uuid', 'misa-unit-uuid'),
}

# ─── EXECUTE ──────────────────────────────────────────────────────────────────

print("=" * 60)
print("Populate MISA IDs vào Odoo records")
print("=" * 60)

# 1) Đơn vị tính
print("\n[UoM]")
for uom_name, misa_unit_id in UNIT_MAP.items():
    if not misa_unit_id:
        print(f"  SKIP {uom_name!r} (chưa có ID)")
        continue
    uoms = env['uom.uom'].sudo().search([('name', '=', uom_name)])
    if not uoms:
        print(f"  NOT FOUND uom name={uom_name!r}")
        continue
    uoms.write({'misa_unit_id': misa_unit_id})
    print(f"  OK  {uom_name!r} ({len(uoms)} records) → {misa_unit_id}")

# 2) Partner
print("\n[Partner]")
for search_name, (misa_id, misa_code) in PARTNER_MAP.items():
    partners = env['res.partner'].sudo().search([('name', '=', search_name)])
    if not partners:
        # Thử search chứa tên
        partners = env['res.partner'].sudo().search([('name', 'ilike', search_name[:30])])
    if not partners:
        print(f"  NOT FOUND partner name={search_name!r}")
        continue
    partners.write({'misa_account_object_id': misa_id})
    print(f"  OK  {search_name[:50]!r} ({len(partners)} records) → {misa_id}")

# 3) Product
print("\n[Product]")
for prod_code, (misa_item_id, misa_unit_id) in PRODUCT_MAP.items():
    products = env['product.product'].sudo().search([('default_code', '=', prod_code)])
    if not products:
        print(f"  NOT FOUND product code={prod_code!r}")
        continue
    products.write({'misa_inventory_item_id': misa_item_id})
    print(f"  OK  code={prod_code!r} ({len(products)} records) → item_id={misa_item_id}")
    # Cũng cập nhật uom nếu chưa có
    for p in products:
        uom = p.uom_id
        if uom and not uom.misa_unit_id:
            uom.sudo().write({'misa_unit_id': misa_unit_id})
            print(f"      → uom {uom.name!r} cũng được cập nhật unit_id={misa_unit_id}")

env.cr.commit()
print("\nHoàn tất. Đã commit.")
