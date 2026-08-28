# -*- coding: utf-8 -*-
"""
check_hlv_product_search_override.py
=====================================
Debug tại sao module hlv_product_search_override (override search()/name_search()
trên product.product và product.template để hỗ trợ search kiểu OR-theo-token)
có vẻ không có tác dụng trên UI khi gõ "thước milwaukee" trong ô search của
list view Sản phẩm.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell, hoặc odoo-bin shell tại môi trường đang chạy):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_hlv_product_search_override.py
"""

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

QUERY = "thước milwaukee"

section("1. Module state")
mod = env['ir.module.module'].sudo().search([('name', '=', 'hlv_product_search_override')])
if mod:
    print(f"  name={mod.name} state={mod.state} latest_version={mod.latest_version} installed_version={mod.installed_version}")
else:
    print("  KHÔNG TÌM THẤY module hlv_product_search_override trong ir_module_module")

section("2. MRO của product.product / product.template (kiểm tra class của mình có được nạp không)")
Product = env['product.product']
Template = env['product.template']
for label, model in [("product.product", Product), ("product.template", Template)]:
    print(f"\n  -- {label} --")
    for c in type(model).__mro__:
        mod_name = getattr(c, '__module__', '')
        if 'hlv_product_search_override' in mod_name or c.__name__ in ('ProductProduct', 'ProductTemplate'):
            print(f"     {mod_name}.{c.__name__}")

section("3. Import trực tiếp common.py và test rewrite_free_text_domain()")
try:
    from odoo.addons.hlv_product_search_override.models.common import (
        rewrite_free_text_domain, tokenize_or_domain, PRODUCT_SEARCH_FIELDS, TEMPLATE_SEARCH_FIELDS,
    )
    print("  import OK")
    domain_product = ['|', '|', ('default_code', 'ilike', QUERY), ('name', 'ilike', QUERY), ('barcode', 'ilike', QUERY)]
    domain_template = ['|', '|', '|', ('default_code', 'ilike', QUERY), ('product_variant_ids.default_code', 'ilike', QUERY), ('name', 'ilike', QUERY), ('barcode', 'ilike', QUERY)]
    print("  domain_product  IN :", domain_product)
    print("  domain_product  OUT:", rewrite_free_text_domain(list(domain_product), fields=PRODUCT_SEARCH_FIELDS))
    print("  domain_template IN :", domain_template)
    print("  domain_template OUT:", rewrite_free_text_domain(list(domain_template), fields=TEMPLATE_SEARCH_FIELDS))
except Exception as e:
    print("  LỖI khi import/chạy common.py:", repr(e))

section("4. Gọi thẳng Product.search(domain_product) — bỏ qua UI/RPC, test thuần Python")
try:
    res = Product.search(domain_product)
    print(f"  Tổng: {len(res)} kết quả")
    for p in res[:15]:
        print(f"    [{p.default_code}] {p.name}")
except Exception as e:
    print("  LỖI:", repr(e))

section("5. Gọi Template.search(domain_template)")
try:
    res_t = Template.search(domain_template)
    print(f"  Tổng: {len(res_t)} kết quả")
    for p in res_t[:15]:
        print(f"    [{p.default_code}] {p.name}")
except Exception as e:
    print("  LỖI:", repr(e))

section("6. Mô phỏng RPC mà web client thật sự gọi (search_read / web_search_read)")
try:
    res_sr = Product.search_read(domain_product, ['default_code', 'name'], limit=80)
    print(f"  search_read: {len(res_sr)} kết quả")
    for r in res_sr[:15]:
        print(f"    [{r['default_code']}] {r['name']}")
except Exception as e:
    print("  search_read LỖI:", repr(e))

try:
    res_wsr = Product.web_search_read(domain_product, {'default_code': {}, 'display_name': {}}, limit=80)
    count = res_wsr.get('length') if isinstance(res_wsr, dict) else None
    records = res_wsr.get('records', []) if isinstance(res_wsr, dict) else []
    print(f"  web_search_read: length={count}, records_returned={len(records)}")
    for r in records[:15]:
        print(f"    [{r.get('default_code')}] {r.get('display_name')}")
except Exception as e:
    print("  web_search_read LỖI:", repr(e))

section("XONG")
