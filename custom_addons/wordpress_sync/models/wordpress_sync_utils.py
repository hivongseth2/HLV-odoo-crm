# -*- coding: utf-8 -*-
"""
Hàm thuần cho việc khớp sản phẩm Odoo với sản phẩm WooCommerce.
Không đụng env, không gọi mạng.
"""
import base64
import hashlib
import hmac

STATE_LINKED = 'linked'
STATE_CASE_MISMATCH = 'case_mismatch'
STATE_DUPLICATE = 'duplicate'
STATE_ORPHAN = 'orphan'
STATE_NO_SKU = 'no_sku'


def normalize_sku(sku):
    """
    Chuẩn hoá SKU để so mà bỏ qua lệch hoa/thường và khoảng trắng hai đầu.

    Nhận: chuỗi, hoặc None/False.
    Trả: chuỗi đã strip và viết hoa; None/False/'' trả ''.
    """
    return (sku or '').strip().upper()


def catalogue_entry(raw, parent_id=0, fallback_name=''):
    """
    Rút gọn một sản phẩm WooCommerce (JSON REST v3) thành các field của bảng liên kết.

    Nhận:
      raw: dict sản phẩm hoặc biến thể, tối thiểu có 'id'.
      parent_id: ID cha khi raw lấy từ /products/<cha>/variations — endpoint đó không
                 trả parent_id và type.
      fallback_name: tên dùng khi raw không có 'name' (biến thể ở WooCommerce cũ).
    Trả: dict wc_product_id, wc_parent_id, wc_type, wc_sku, wc_name, wc_url, wc_status.
      SKU giữ nguyên văn để người dùng thấy đúng cái đang nằm trên web.
    """
    parent = int(raw.get('parent_id') or parent_id or 0)
    return {
        'wc_product_id': int(raw['id']),
        'wc_parent_id': parent,
        'wc_type': raw.get('type') or ('variation' if parent else 'simple'),
        'wc_sku': raw.get('sku') or '',
        'wc_name': raw.get('name') or fallback_name,
        'wc_url': raw.get('permalink') or '',
        'wc_status': raw.get('status') or '',
    }


def should_track(entry):
    """
    Có lưu dòng liên kết cho sản phẩm web này không.

    Sản phẩm 'variable' không SKU chỉ là vỏ chứa biến thể, không bán được; lưu vào thì
    chỉ đẻ ra một đống 'web chưa nhập mã' giả.

    Nhận: dict từ catalogue_entry.
    Trả: False cho vỏ variable không SKU, True cho mọi trường hợp khác.
    """
    return not (entry['wc_type'] == 'variable' and not entry['wc_sku'])


def match_entries(entries, odoo_codes):
    """
    Gán sản phẩm Odoo cho từng sản phẩm web theo SKU.

    Nhận:
      entries: list dict có 'wc_product_id' và 'wc_sku'. Phải gồm TẤT CẢ sản phẩm web cùng
               SKU chuẩn hoá với nhau — thiếu thì không phát hiện được trùng mã trên web.
      odoo_codes: list (product_id, default_code) phía Odoo; thừa mã không liên quan cũng được.
    Trả: dict {wc_product_id: (product_id hoặc False, state)}:
      - SKU web rỗng                              → (False, 'no_sku')
      - Odoo không có mã                          → (False, 'orphan')
      - Nhiều sản phẩm Odoo cùng mã               → (False, 'duplicate')
      - Khớp một sản phẩm Odoo, web có nhiều dòng → (id, 'duplicate'), vẫn đẩy giá lên tất cả
      - Khớp đúng từng ký tự                      → (id, 'linked')
      - Chỉ khớp sau khi chuẩn hoá                → (id, 'case_mismatch')
    """
    odoo_by_norm = {}
    for product_id, code in odoo_codes:
        norm = normalize_sku(code)
        if norm:
            odoo_by_norm.setdefault(norm, []).append((product_id, code))

    web_count = {}
    for entry in entries:
        norm = normalize_sku(entry['wc_sku'])
        web_count[norm] = web_count.get(norm, 0) + 1

    result = {}
    for entry in entries:
        sku = entry['wc_sku'] or ''
        norm = normalize_sku(sku)
        if not norm:
            result[entry['wc_product_id']] = (False, STATE_NO_SKU)
            continue

        candidates = odoo_by_norm.get(norm, [])
        exact = [product_id for product_id, code in candidates if code == sku]
        if len(exact) == 1:
            product_id, state = exact[0], STATE_LINKED
        elif len(candidates) == 1:
            product_id, state = candidates[0][0], STATE_CASE_MISMATCH
        elif candidates:
            product_id, state = False, STATE_DUPLICATE
        else:
            product_id, state = False, STATE_ORPHAN

        if product_id and web_count[norm] > 1:
            state = STATE_DUPLICATE
        result[entry['wc_product_id']] = (product_id, state)
    return result


def chunked(items, size):
    """
    Chia list thành các đoạn liên tiếp dài tối đa size.

    Nhận: list, size > 0.
    Trả: list các list con; items rỗng trả [].
    """
    return [items[i:i + size] for i in range(0, len(items), size)]


def wc_signature_valid(body, secret, signature):
    """
    Kiểm chữ ký webhook WooCommerce: base64(HMAC-SHA256(body, secret)).

    Nhận: body là bytes nguyên văn của request, secret là chuỗi đã khai ở webhook,
          signature là giá trị header X-WC-Webhook-Signature.
    Trả: True nếu khớp; secret hoặc signature rỗng trả False.
    """
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode(), body or b'', hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature.strip())
