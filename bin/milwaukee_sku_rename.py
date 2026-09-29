# -*- coding: utf-8 -*-
"""
milwaukee_sku_rename.py
=======================
Bỏ chữ "MILWAUKEE" khỏi Tham chiếu nội bộ (default_code) và đổi theo ở MISA CRM +
WooCommerce. Mặc định APPLY = False: chỉ tra cứu và in kế hoạch, không ghi gì.

Ba nơi phải khớp mã:

  1. Odoo       — mã mới không được đụng sản phẩm khác. Đụng hàng ĐÃ LƯU TRỮ thì xoá
                  tham chiếu của hàng lưu trữ (người dùng chốt 2026-09-28: lưu trữ là bỏ).
  2. MISA CRM   — script tự gọi update_product_field_misa. Hook write tự đẩy mã sang CRM
                  (misa_fetch_po_button/models/product_misa_sync.py) đã bị TẮT từ commit
                  "hot fix" 2026-03-05, nên đổi mã trong Odoo KHÔNG tự sang CRM. CRM đã có
                  mã mới thì CRM từ chối (ProductCode IsUnique) → dòng đó phải bỏ qua.
  3. WordPress  — wordpress_sync KHÔNG đẩy đổi SKU, mà lại tìm sản phẩm web theo SKU, nên
                  web đang dùng mã cũ thì phải đổi SKU web trước khi đổi Odoo.

Chạy:
    python odoo-bin shell -d <DATABASE> --no-http < bin/milwaukee_sku_rename.py
"""
import logging
import re

from odoo.addons.wordpress_sync.models.wordpress_api import WooCommerceAPI

env = env  # noqa: F821

# --- CẤU HÌNH ---
APPLY = True        # False = chỉ in kế hoạch | True = ghi thật (web → Odoo → CRM), commit từng dòng
KEYWORD = 'milwaukee'
ONLY_CODES = {       # để trống = cả đợt; có mã = chỉ chạy các mã này (thử mẫu)

}
SKIP_CODES = {
    '48-22-8497-MILWAUKEE',   # web có 2 sản phẩm (63161 mã cũ, 60805 mã mới) — chờ marketing
}
CRM_FIX = {          # mã cũ → misa_id: Odoo + web đã đổi, CRM còn mã cũ — chỉ sửa CRM
}
# ----------------

SEP = r'[\s\-_./]*'
_SUFFIX = re.compile(r'^(?P<core>.*?)' + SEP + KEYWORD + SEP + r'$', re.IGNORECASE)
_PREFIX = re.compile(r'^' + SEP + KEYWORD + SEP + r'(?P<core>.*)$', re.IGNORECASE)

# misa_api_utils log nguyên body JSON mỗi lần tìm, lấp mất dòng tiến độ của script.
logging.getLogger('odoo.addons.misa_fetch_po_button.utils.misa_api_utils').setLevel(logging.WARNING)


def propose_code(code):
    """Bỏ KEYWORD ở đầu hoặc cuối mã cùng dấu nối liền kề.

    Nhận: mã hiện tại (str).
    Trả: mã mới (str), hoặc None khi KEYWORD nằm giữa mã hay bỏ xong thì rỗng —
    những mã đó phải xem tay, không đoán.
    """
    for pattern in (_SUFFIX, _PREFIX):
        match = pattern.match(code or '')
        if match:
            core = match.group('core').strip()
            if core and KEYWORD not in core.lower():
                return core
    return None


def print_row(*cols):
    print(' | '.join(str(c) for c in cols))


# ── 1. Odoo ─────────────────────────────────────────────────────────────────
Variant = env['product.product'].sudo().with_context(active_test=False)

domain = [('default_code', 'ilike', KEYWORD)]
if ONLY_CODES:
    domain.append(('default_code', 'in', list(ONLY_CODES)))

rows = []
for var in Variant.search(domain, order='default_code'):
    tmpl = var.product_tmpl_id
    new = propose_code(var.default_code)
    rows.append({
        'tmpl': tmpl, 'var': var, 'old': var.default_code, 'new': new,
        'active': var.active and tmpl.active,
        'multi': tmpl.product_variant_count > 1,
        'clash': Variant.search([('default_code', '=ilike', new), ('id', '!=', var.id)])
                 if new else Variant.browse(),
        'misa_old': None, 'misa_new': None, 'misa_err': None,
        'wp_old': [], 'wp_new': [], 'wp_err': False,
    })

# Hai mã cũ khác nhau có thể ra cùng một mã mới (vd "X-MILWAUKEE" và "X MILWAUKEE").
new_counts = {}
for row in rows:
    if row['new']:
        new_counts[row['new'].upper()] = new_counts.get(row['new'].upper(), 0) + 1


# ── 2. MISA CRM ─────────────────────────────────────────────────────────────
def misa_lookup(misa_utils, old, new):
    """Trả (misa_id của mã cũ, misa_id của mã mới, lỗi).

    Tìm "chứa <mã mới>" một lần là đủ: mã cũ luôn chứa mã mới.
    """
    try:
        found = misa_utils.search_product_by_name(code=new, limit=50) or []
    except Exception as e:
        return None, None, str(e)
    by_code = {(p.get('code') or '').upper(): p.get('misa_id') for p in found}
    return by_code.get(old.upper()), by_code.get(new.upper()), None


misa_utils = env['misa.api.utils'] if 'misa.api.utils' in env else None
if misa_utils is None:
    print('!! Không có model misa.api.utils — không kiểm được CRM, sẽ không ghi gì')
for i, row in enumerate(rows, 1):
    if misa_utils is None:
        row['misa_err'] = 'không có misa.api.utils'
    elif row['new']:
        print('MISA %s/%s %s' % (i, len(rows), row['old']))
        row['misa_old'], row['misa_new'], row['misa_err'] = misa_lookup(
            misa_utils, row['old'], row['new'])


# ── 3. WordPress ────────────────────────────────────────────────────────────
def wp_lookup(api, sku):
    """Trả (list sản phẩm, có lỗi không). _get trả None khi lỗi, [] khi không thấy."""
    data = api._get('%s/products?sku=%s&per_page=100' % (api.base_url, sku))
    return (data or []), data is None


def wp_describe(items):
    return ', '.join('%s(%s%s)' % (
        it.get('id'), it.get('type'),
        ',cha=%s' % it['parent_id'] if it.get('parent_id') else '') for it in items)


def wp_set_sku(api, item, sku):
    """Đổi SKU một sản phẩm web. Trả True khi WooCommerce nhận."""
    is_variation = item.get('type') == 'variation'
    return bool(api.update_product(item['id'], {'sku': sku},
                                   is_variation=is_variation,
                                   parent_id=item.get('parent_id')))


config = env['wordpress.config'].sudo().search([('active', '=', True)], limit=1)
api = WooCommerceAPI(config.wc_domain, *config.get_credentials()) if config else None
if api is None:
    print('!! Không có wordpress.config đang bật — không kiểm được web, sẽ không ghi gì')
for i, row in enumerate(rows, 1):
    if api is None:
        row['wp_err'] = True
        continue
    print('WP %s/%s %s' % (i, len(rows), row['old']))
    row['wp_old'], old_err = wp_lookup(api, row['old'])
    if row['new']:
        row['wp_new'], new_err = wp_lookup(api, row['new'])
    else:
        new_err = False
    row['wp_err'] = old_err or new_err


# ── 4. Kế hoạch ─────────────────────────────────────────────────────────────
def decide(row):
    """Trả (việc, ghi chú). Việc: 'rename' | 'clear_self' | 'skip'."""
    if row['old'] in SKIP_CODES:
        return 'skip', 'bỏ qua theo yêu cầu'
    if not row['new']:
        return 'skip', 'mã lạ - xem tay'
    if row['multi']:
        # Ghi default_code trên template nhiều biến thể không đổ xuống biến thể nào.
        return 'skip', 'nhiều biến thể'
    if new_counts[row['new'].upper()] > 1:
        return 'skip', 'trùng mã mới trong đợt'
    if row['misa_err'] or row['wp_err']:
        return 'skip', 'lỗi tra cứu (MISA: %s, WP: %s) - chạy lại' % (
            row['misa_err'] or 'ok', 'lỗi' if row['wp_err'] else 'ok')

    active_clash = row['clash'].filtered(lambda v: v.active and v.product_tmpl_id.active)
    archived_clash = row['clash'] - active_clash

    if not row['active'] and active_clash:
        # Bản sạch đang dùng đã có sẵn; bản -MILWAUKEE lưu trữ chỉ cần bỏ tham chiếu.
        if row['wp_old']:
            return 'skip', 'hàng lưu trữ nhưng web còn dùng mã cũ %s' % wp_describe(row['wp_old'])
        return 'clear_self', 'xoá tham chiếu hàng lưu trữ; bản dùng: %s' % ', '.join(
            '[%s]' % v.id for v in active_clash)
    if active_clash:
        return 'skip', 'trùng sản phẩm đang dùng %s' % ', '.join(
            '[%s] %s' % (v.id, v.display_name) for v in active_clash)
    if not row['active'] and archived_clash:
        return 'skip', 'hai bản lưu trữ trùng mã - xem tay'
    if row['misa_new']:
        return 'skip', 'CRM đã có mã mới (id=%s)' % row['misa_new']
    if len(row['wp_old']) > 1:
        return 'skip', 'web có nhiều sản phẩm mã cũ %s' % wp_describe(row['wp_old'])
    if row['wp_old'] and row['wp_new']:
        return 'skip', 'web có cả mã cũ %s và mã mới %s' % (
            wp_describe(row['wp_old']), wp_describe(row['wp_new']))

    notes = []
    if archived_clash:
        notes.append('xoá tham chiếu lưu trữ %s' % ', '.join('[%s]' % v.id for v in archived_clash))
    if row['wp_old']:
        notes.append('đổi SKU web %s' % wp_describe(row['wp_old']))
    elif row['wp_new']:
        notes.append('nối lại web %s' % wp_describe(row['wp_new']))
    notes.append('CRM id=%s' % row['misa_old'] if row['misa_old'] else 'CRM không có')
    if not row['active']:
        notes.append('hàng lưu trữ')
    return 'rename', '; '.join(notes)


for row in rows:
    row['action'], row['note'] = decide(row)

print()
print('=' * 110)
print('KẾ HOẠCH (%s dòng)%s' % (len(rows), '' if APPLY else '  —  CHẠY THỬ, chưa ghi gì'))
print('=' * 110)
print_row('tmpl_id', 'mã cũ', '→ mã mới', 'việc', 'ghi chú', 'tên')
for row in rows:
    target = row['new'] if row['action'] == 'rename' else ('(xoá)' if row['action'] == 'clear_self' else '-')
    print_row(row['tmpl'].id, row['old'], target, row['action'], row['note'], row['tmpl'].name)

for action in ('rename', 'clear_self', 'skip'):
    print('%-10s %s' % (action, sum(1 for r in rows if r['action'] == action)))


# ── 5. Ghi ──────────────────────────────────────────────────────────────────
def crm_set_code(misa_id, new, old):
    """Đổi ProductCode bên CRM. Trả True khi MISA nhận (lỗi thì misa_api_utils log WARNING)."""
    return bool(misa_utils.update_product_field_misa(str(misa_id), 'code', new, old))


def undo_web(row, web_item):
    if not web_item:
        return ''
    if wp_set_sku(api, web_item, row['old']):
        return ' (đã trả SKU web về cũ)'
    return ' — VÀ KHÔNG TRẢ ĐƯỢC SKU WEB %s VỀ %s, SỬA TAY' % (web_item['id'], row['old'])


def apply_rename(row):
    """Web → Odoo (chưa commit) → CRM → commit. Hỏng bước nào thì gỡ các bước trước.

    Odoo ghi trước CRM để lỗi ràng buộc DB lộ ra khi còn rollback được; CRM là bước
    gọi ra ngoài cuối cùng trước commit.
    """
    web_item = row['wp_old'][0] if row['wp_old'] else None
    if web_item and not wp_set_sku(api, web_item, row['new']):
        return 'LỖI: web không nhận SKU mới, chưa đổi gì'
    try:
        row['clash'].write({'default_code': False})   # hàng lưu trữ: chỉ bỏ ở Odoo
        row['tmpl'].write({'default_code': row['new']})
        env.flush_all()
    except Exception as e:
        env.cr.rollback()
        return 'LỖI Odoo: %s%s' % (e, undo_web(row, web_item))
    if row['misa_old'] and not crm_set_code(row['misa_old'], row['new'], row['old']):
        env.cr.rollback()
        return 'LỖI CRM: MISA không nhận mã mới, đã huỷ Odoo%s' % undo_web(row, web_item)
    env.cr.commit()
    return 'xong'


def apply_clear_self(row):
    try:
        row['var'].write({'default_code': False})
        env.cr.commit()
    except Exception as e:
        env.cr.rollback()
        return 'LỖI Odoo: %s' % e
    return 'xong'


def verify_crm(old, new):
    """Tra lại CRM sau khi đổi. Grid MISA có cache (IsGetCache) nên có thể còn thấy mã cũ
    ngay sau khi đổi — khi đó mở CRM xem tay trước khi sửa lại."""
    old_id, new_id, err = misa_lookup(misa_utils, old, new)
    if err:
        return 'CRM: không tra lại được (%s)' % err
    if new_id and not old_id:
        return 'CRM: đã đổi'
    return 'CRM: tra lại vẫn thấy mã cũ (có thể do cache) - xem tay'


if APPLY and CRM_FIX and misa_utils is not None:
    print()
    print('=' * 110)
    print('SỬA CRM cho mã đã đổi ở Odoo')
    print('=' * 110)
    for old, misa_id in CRM_FIX.items():
        new = propose_code(old)
        if not crm_set_code(misa_id, new, old):
            print_row(misa_id, old, new, 'LỖI: MISA không nhận, xem dòng ⚠️ phía trên')
            continue
        print_row(misa_id, old, new, 'xong ' + verify_crm(old, new))

if APPLY:
    print()
    print('=' * 110)
    print('GHI')
    print('=' * 110)
    for row in rows:
        if row['action'] == 'rename':
            result = apply_rename(row)
            if result == 'xong' and row['misa_old']:
                result = 'xong ' + verify_crm(row['old'], row['new'])
        elif row['action'] == 'clear_self':
            result = apply_clear_self(row)
        else:
            continue
        print_row(row['tmpl'].id, row['old'], row['action'], result)
