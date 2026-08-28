# -*- coding: utf-8 -*-
"""
check_search_internal_signature.py
===================================
Bước tiếp theo sau bin/check_hlv_product_search_override.py: đã xác nhận
search_read()/web_search_read() KHÔNG đi qua search() công khai (bypass hoàn
toàn override của hlv_product_search_override), nên phải override _search()
(hàm nội bộ) thay vì search(). Script này soi chữ ký thật của _search() +
các hàm liên quan (search_fetch, _search_panel..., v.v.) trên product.product
để viết override đúng tham số, tránh đoán mò.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy:
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_search_internal_signature.py
"""
import inspect

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

Product = env['product.product']
Model = type(Product)

section("1. Chữ ký các hàm search-liên-quan trên product.product (class thật đang chạy)")
for fname in ['search', '_search', 'search_fetch', 'search_read', 'web_search_read', '_search_panel_domain_image', 'search_count']:
    fn = getattr(Model, fname, None)
    if fn is None:
        print(f"  {fname}: KHÔNG TỒN TẠI")
        continue
    try:
        sig = inspect.signature(fn)
        owner_module = getattr(fn, '__module__', '?')
        print(f"  {fname}{sig}")
        print(f"      định nghĩa gốc ở: {owner_module}")
    except Exception as e:
        print(f"  {fname}: lỗi lấy signature -> {e!r}")

section("2. Trace thử: patch tạm _search bằng bản in log rồi gọi web_search_read để xem có bị gọi không")
import types
orig_search = Model._search
calls = []
def traced_search(self, domain, *args, **kwargs):
    calls.append((tuple(domain) if domain else (), args, kwargs))
    return orig_search(self, domain, *args, **kwargs)
Model._search = traced_search
try:
    Product.web_search_read(
        [('name', 'ilike', 'milwaukee')],
        {'display_name': {}},
        limit=5,
    )
finally:
    Model._search = orig_search

print(f"  _search() bị gọi {len(calls)} lần trong quá trình web_search_read()")
for c in calls:
    print("   domain:", c[0])
    print("   args/kwargs:", c[1], c[2])

section("XONG")
