# -*- coding: utf-8 -*-
"""Gọt dữ liệu trang tra giá NCC (hlv_vendor_quotation.price_lookup.product_prices) cho trợ lý.

Bản gốc dựng cho trang web: tới 200 lần mua + 200 báo giá, mỗi dòng hơn chục trường. Đưa
nguyên cho model là tốn token mà phần lớn không dùng tới khi gợi ý giá mua: chỉ giữ tóm tắt
theo NCC, vài lần mua và báo giá gần nhất, mỗi dòng các trường quyết định giá.

Util thuần: vào dict, ra dict. Không đụng ``self.env``.
"""

PURCHASE_ROWS = 10
QUOTE_ROWS = 15
VENDOR_ROWS = 10


def _purchase(row):
    return row and {
        'ngay': row.get('day'), 'ncc': row.get('vendor'), 'gia': round(row.get('price') or 0),
        'sl': row.get('qty'), 'dvt': row.get('uom'), 'don': row.get('order'),
        # Lần mua đã trả NCC (một phần / hết) không còn là giá chốt thật.
        'tra_hang': row.get('return_state') or '',
    }


def _quote(row):
    return row and {
        'ngay': row.get('day'), 'ncc': row.get('vendor'), 'gia': round(row.get('price') or 0),
        'vat': row.get('vat'), 'sl': row.get('qty'), 'giao_ngay': row.get('delivery_days'),
        'het_hang': bool(row.get('unavailable')), 'hieu_luc_den': row.get('valid_until') or '',
        # reusable = còn hạn, dùng lại để báo khách được (price_reuse.reuse_block_reason).
        'con_dung_duoc': bool(row.get('reusable')), 'ly_do_het_dung': row.get('reuse_note') or '',
    }


def compact_prices(prices, link):
    """Bản gọn của product_prices cho trợ lý gợi ý giá mua.

    Nhận: dict {vendors, purchases, quotes} (mới nhất trước) và link trang tra giá của mã.
    Trả: {'link_tra_gia', 'theo_ncc', 'lan_mua', 'bao_gia', 'tong_lan_mua', 'tong_bao_gia'};
    giá đều SAU VAT, làm tròn đồng. Biên: thiếu khoá nào thì coi như list rỗng.
    """
    purchases = prices.get('purchases') or []
    quotes = prices.get('quotes') or []
    return {
        'link_tra_gia': link,
        'theo_ncc': [{
            'ncc': item.get('vendor'),
            'mua_gan_nhat': _purchase(item.get('last_purchase')),
            'mua_thap_nhat': _purchase(item.get('min_purchase')),
            'so_lan_mua': item.get('purchase_count', 0),
            'bao_gan_nhat': _quote(item.get('last_quote')),
            'bao_thap_nhat': _quote(item.get('min_quote')),
            'so_lan_bao': item.get('quote_count', 0),
        } for item in (prices.get('vendors') or [])[:VENDOR_ROWS]],
        'lan_mua': [_purchase(row) for row in purchases[:PURCHASE_ROWS]],
        'bao_gia': [_quote(row) for row in quotes[:QUOTE_ROWS]],
        'tong_lan_mua': len(purchases),
        'tong_bao_gia': len(quotes),
    }
