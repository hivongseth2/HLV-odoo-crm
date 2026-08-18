# -*- coding: utf-8 -*-
"""
recompute_combo_prices.py
==========================
Tính lại 3 giá của TẤT CẢ sản phẩm combo (BOM Kit / phantom):
  - x_studio_gia_san_tmdt   (Giá Sàn TMĐT)
  - x_studio_gi_bn_thng_mi  (Giá Thương Mại)
  - x_studio_ga_web         (Giá Web)     -- đã tự tính từ trước, tính lại cho đồng bộ
  - x_studio_ga_hng_nim_yt  (Giá Niêm Yết) -- đã tự tính từ trước, tính lại cho đồng bộ

KHÔNG đụng tới list_price (Giá bán lẻ) của sản phẩm combo.

Dùng lại logic gốc: product.template._compute_combo_selling_price()
(custom_addons/wordpress_sync/models/product_template.py) để đảm bảo
kết quả giống hệt cơ chế auto-update khi có thay đổi giá linh kiện.

Chạy:
    python odoo-bin shell -d <DATABASE> --no-http < bin/recompute_combo_prices.py
"""

import logging

_logger = logging.getLogger(__name__)

BATCH_SIZE = 200

FIELDS_TO_WATCH = [
    'x_studio_ga_web',
    'x_studio_ga_hng_nim_yt',
    'x_studio_gia_san_tmdt',
    'x_studio_gi_bn_thng_mi',
]

Template = env['product.template'].sudo()
Bom = env['mrp.bom'].sudo()

boms = Bom.search([('type', '=', 'phantom'), ('active', '=', True)])
combo_templates = boms.mapped('product_tmpl_id')

print("=" * 100)
print("Tim thay %d san pham combo (co BOM phantom active)" % len(combo_templates))
print("=" * 100)

updated_count = 0
unchanged_count = 0
skipped_no_price = 0

combo_ids = combo_templates.ids
for i in range(0, len(combo_ids), BATCH_SIZE):
    batch_ids = combo_ids[i:i + BATCH_SIZE]
    batch = Template.browse(batch_ids)

    # Chup gia truoc khi tinh lai de so sanh
    before = {
        tmpl.id: {f: tmpl[f] for f in FIELDS_TO_WATCH}
        for tmpl in batch
    }

    batch._compute_combo_selling_price()

    batch.invalidate_recordset(FIELDS_TO_WATCH + ['computed_combo_selling_price'])

    for tmpl in batch:
        after = {f: tmpl[f] for f in FIELDS_TO_WATCH}
        old = before[tmpl.id]

        if all((old[f] or 0.0) == 0.0 for f in FIELDS_TO_WATCH) and all((after[f] or 0.0) == 0.0 for f in FIELDS_TO_WATCH):
            skipped_no_price += 1
            continue

        if old != after:
            updated_count += 1
            print(
                "[%s] %s" % (tmpl.default_code or tmpl.id, tmpl.name)
            )
            for f in FIELDS_TO_WATCH:
                if old[f] != after[f]:
                    print("    %-26s %s -> %s" % (f, old[f], after[f]))
        else:
            unchanged_count += 1

    env.cr.commit()
    print("-- Da xu ly %d/%d combo --" % (min(i + BATCH_SIZE, len(combo_ids)), len(combo_ids)))

print("=" * 100)
print("HOAN TAT")
print("  Tong combo:        %d" % len(combo_templates))
print("  Da cap nhat gia:   %d" % updated_count)
print("  Khong doi:         %d" % unchanged_count)
print("  Khong co gia con:  %d" % skipped_no_price)
print("=" * 100)
