#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inspect Shopee product/linking models on a live Odoo database.

Chạy trên Odoo.sh shell:
    odoo-bin shell -d <database_name> < bin/inspect_shopee_product_links.py

Script chỉ đọc dữ liệu. Mục tiêu là xác nhận cấu trúc thật của sale_shopee / shopee.item
và quan hệ tới product.product trước khi nối module shopee_product vào dữ liệu sẵn có.
"""

SEP = "=" * 96
SEP2 = "-" * 96


def print_title(title):
    print("\n" + SEP)
    print(title)
    print(SEP)


def field_summary(model_name):
    if model_name not in env:
        print(f"[MISSING MODEL] {model_name}")
        return

    model = env[model_name]
    print_title(f"MODEL: {model_name}")
    print(f"Description : {getattr(model, '_description', '')}")
    print(f"Table       : {getattr(model, '_table', '')}")
    print(f"Rec name    : {getattr(model, '_rec_name', '')}")
    print(f"Order       : {getattr(model, '_order', '')}")
    print("\nFields:")
    print(f"  {'field':<34} {'type':<12} {'relation':<28} {'store':<6} {'required':<8} string")
    print(SEP2)
    for name in sorted(model._fields):
        field = model._fields[name]
        relation = getattr(field, 'comodel_name', '') or getattr(field, 'relation', '') or ''
        print(
            f"  {name:<34} {field.type:<12} {relation:<28} "
            f"{str(getattr(field, 'store', '')):<6} {str(getattr(field, 'required', '')):<8} "
            f"{getattr(field, 'string', '')}"
        )


def installed_shopee_modules():
    print_title("INSTALLED MODULES CONTAINING 'shopee'")
    modules = env['ir.module.module'].sudo().search(
        [('name', 'ilike', 'shopee'), ('state', '=', 'installed')],
        order='name',
    )
    for module in modules:
        print(f"  {module.name:<40} {module.shortdesc or ''}")
    if not modules:
        print("  (none)")


def registry_shopee_models():
    print_title("REGISTRY MODELS CONTAINING 'shopee'")
    names = sorted(name for name in env if 'shopee' in name)
    for name in names:
        model = env[name]
        print(f"  {name:<40} table={getattr(model, '_table', '')}")
    if not names:
        print("  (none)")


def sample_shopee_items(limit=20):
    if 'shopee.item' not in env:
        return

    Model = env['shopee.item'].sudo()
    fields = Model._fields
    preferred = [
        'id',
        'display_name',
        'name',
        'shop_id',
        'shopee_item_identifier',
        'shopee_model_identifier',
        'item_id',
        'model_id',
        'item_sku',
        'model_sku',
        'sku',
        'product_id',
        'product_tmpl_id',
    ]
    cols = [field for field in preferred if field == 'id' or field in fields]
    records = Model.search([], limit=limit, order='id desc')

    print_title(f"SAMPLE shopee.item RECORDS (latest {limit})")
    print("  " + " | ".join(cols))
    print(SEP2)
    for rec in records:
        row = []
        for col in cols:
            if col == 'id':
                row.append(str(rec.id))
                continue
            val = rec[col]
            if hasattr(val, 'display_name'):
                row.append(f"{val.display_name} ({val.id})" if val else "")
            else:
                row.append(str(val or ''))
        print("  " + " | ".join(row))
    if not records:
        print("  (no records)")


def compare_with_shopee_product(limit=30):
    print_title("COMPARE shopee.product VS shopee.item")
    if 'shopee.product' not in env:
        print("  shopee.product is not installed in this DB.")
        return
    if 'shopee.item' not in env:
        print("  shopee.item is not installed in this DB.")
        return

    Product = env['shopee.product'].sudo()
    Item = env['shopee.item'].sudo()
    product_count = Product.search_count([])
    item_count = Item.search_count([])
    print(f"  shopee.product count : {product_count}")
    print(f"  shopee.item count    : {item_count}")

    item_fields = Item._fields
    item_id_field = 'shopee_item_identifier' if 'shopee_item_identifier' in item_fields else 'item_id'
    model_id_field = 'shopee_model_identifier' if 'shopee_model_identifier' in item_fields else 'model_id'

    missing = []
    linked = []
    for prod in Product.search([], limit=limit, order='id desc'):
        domain = [(item_id_field, '=', str(prod.shopee_item_id))]
        item = Item.search(domain, limit=1)
        if not item and item_id_field in item_fields:
            domain = [(item_id_field, '=', prod.shopee_item_id)]
            item = Item.search(domain, limit=1)
        if item:
            linked.append((prod, item))
        else:
            missing.append(prod)

    print(f"\n  Checked latest shopee.product records : {min(product_count, limit)}")
    print(f"  Found matching shopee.item            : {len(linked)}")
    print(f"  Missing matching shopee.item          : {len(missing)}")

    if linked:
        print("\n  Matched examples:")
        for prod, item in linked[:10]:
            mapped_product = item.product_id.display_name if 'product_id' in item_fields and item.product_id else ''
            model_id = item[model_id_field] if model_id_field in item_fields else ''
            print(
                f"    shopee.product {prod.id} item_id={prod.shopee_item_id} "
                f"-> shopee.item {item.id} model_id={model_id} product={mapped_product}"
            )

    if missing:
        print("\n  Missing examples:")
        for prod in missing[:10]:
            print(f"    shopee.product {prod.id} item_id={prod.shopee_item_id} name={prod.item_name}")


installed_shopee_modules()
registry_shopee_models()

for model_name in [
    'shopee.item',
    'shopee.product',
    'shopee.product.model',
    'product.product',
    'product.template',
    'sale.order.line',
]:
    field_summary(model_name)

sample_shopee_items()
compare_with_shopee_product()

print("\nDONE: read-only inspection complete.")