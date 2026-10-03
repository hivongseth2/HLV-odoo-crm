# -*- coding: utf-8 -*-
"""Câu tóm tắt thay đổi combo cho sale / quản lý đọc.

Util thuần: vào dict, ra chuỗi. Không đụng ``self.env``.
"""

_HEADER_LABELS = {'ProductName': 'tên', 'UnitPrice': 'giá bán', 'PurchasedPrice': 'giá nhập'}


def combo_change_summary(changes, header):
    """Tóm tắt một lần sửa combo.

    Nhận: ``changes`` = ``{'added': [(mã, sl)], 'removed': [(mã, sl)],
        'changed': [(mã, sl_cũ, sl_mới)]}`` (xem crm_combo_payload.diff_combo_rows của
        misa_fetch_po_button), ``header`` = trường phần đầu đã đổi ``{'ProductName': ...}``.
    Trả: vd ``"thêm 0138M x2; bỏ 0163M; 0-39-055 1→2; tên → Bộ khóa mới"``.
    Biên: không có gì đổi -> ``"không đổi"``.
    """
    parts = ["thêm %s x%g" % (code, qty) for code, qty in changes.get('added') or []]
    parts += ["bỏ %s" % code for code, _qty in changes.get('removed') or []]
    parts += ["%s %g→%g" % (code, old, new) for code, old, new in changes.get('changed') or []]
    parts += ["%s → %s" % (_HEADER_LABELS.get(key, key), value) for key, value in (header or {}).items()]
    return "; ".join(parts) or "không đổi"
