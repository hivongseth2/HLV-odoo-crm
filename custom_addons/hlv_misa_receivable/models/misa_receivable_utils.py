# -*- coding: utf-8 -*-
"""Hàm thuần cho tình trạng thu tiền theo dòng đơn bán và công nợ phải thu.

Thuần theo đúng nghĩa: chỉ nhận dict/date/số, không đụng self.env, không gọi API, không side
effect — phần đọc dòng chứng từ MISA, chia dòng chứng từ về dòng đơn bán, tính quá hạn, chia
nhóm tuổi nợ kiểm chứng được mà không cần Odoo lẫn MISA.
"""
from datetime import date

from odoo.addons.misa_invoice_status_report.models.misa_invoice_amount_utils import (
    invoice_vat_ratio,
    split_by_weights,
    voucher_line_amount_with_vat,
)
from odoo.addons.misa_invoice_status_report.models.misa_invoice_reassign_utils import item_key, name_key
from odoo.addons.misa_invoice_status_report.models.misa_voucher_utils import paid_state_of

# Nhóm tuổi nợ theo số ngày quá hạn (min, max đều tính cả 2 đầu; None = không chặn). Thứ tự ở
# đây là thứ tự hiện trên trang.
AGING_BUCKETS = [
    ('not_due', 'Chưa đến hạn', None, -1),
    ('due_today', 'Đến hạn hôm nay', 0, 0),
    ('1_30', 'Quá hạn 1–30 ngày', 1, 30),
    ('31_60', 'Quá hạn 31–60 ngày', 31, 60),
    ('61_90', 'Quá hạn 61–90 ngày', 61, 90),
    ('over_90', 'Quá hạn trên 90 ngày', 91, None),
]


def parse_misa_date(value):
    """Đọc ngày MISA trả về ("2026-08-28T00:00:00.000+07:00") thành date.

    Chỉ lấy phần ngày theo ĐÚNG chuỗi MISA trả, không đổi múi giờ — MISA đã ghi theo giờ VN,
    đổi qua UTC là lùi mất 1 ngày. Nhận str/None/False. Trả date, hoặc None nếu rỗng/không
    đọc được.
    """
    raw = value.strip() if isinstance(value, str) else ''
    if len(raw) < 10:
        return None
    try:
        return date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        return None


def voucher_payment_entries(voucher, lines):
    """Các dòng hàng của 1 chứng từ bán hàng MISA, mỗi dòng mang theo tình trạng thu tiền.

    MISA chỉ ghi đã thu / chưa thu (paid_type) ở cấp CHỨNG TỪ, không ở từng dòng — nên mọi dòng
    của 1 chứng từ chung 1 paid_state. Tiền có VAT tính bằng voucher_line_amount_with_vat của
    module đối soát (cột VAT của dòng, thiếu thì theo tỉ lệ tổng chứng từ).

    Nhận: voucher — 1 dòng sa_voucher_get; lines — chi tiết của chứng từ đó (get_voucher_lines).
    Trả list dict, rỗng nếu lines rỗng.
    """
    paid_state, _label = paid_state_of(voucher.get('paid_type'))
    ratio = invoice_vat_ratio(voucher.get('total_amount'), [line.get('amount_oc') or 0.0 for line in lines or []])
    head = {
        'voucher_refid': voucher.get('refid') or '',
        'voucher_refno': voucher.get('refno_finance') or '',
        'invoice_date': parse_misa_date(voucher.get('inv_date')),
        'partner_code': voucher.get('account_object_code') or '',
        'partner_name': voucher.get('account_object_name') or '',
        'paid_state': paid_state,
    }
    return [
        dict(
            head,
            order_code=(line.get('order_code') or '').strip(),
            item_code=item_key(line.get('inventory_item_code')),
            description=line.get('description') or '',
            quantity=line.get('quantity') or 0.0,
            unit_name=line.get('unit_name') or '',
            amount=voucher_line_amount_with_vat(line, ratio),
        )
        for line in lines or []
    ]


def _fill_by_capacity(quantity, candidates, remaining):
    """Rót số lượng vào các dòng đơn bán cùng mã hàng, dòng đứng trước nhận trước, mỗi dòng tối
    đa phần sức chứa còn lại; dư thì dồn vào dòng cuối (để không mất tiền). Sửa `remaining` tại
    chỗ — chỉ dùng nội bộ trong allocate_entries. Trả list (candidate, qty)."""
    parts = []
    left = quantity
    for cand in candidates:
        take = min(left, remaining[cand['sale_line_id']])
        if take > 0:
            parts.append([cand, take])
            remaining[cand['sale_line_id']] -= take
            left -= take
    if left > 0:
        if parts and parts[-1][0] is candidates[-1]:
            parts[-1][1] += left
        else:
            parts.append([candidates[-1], left])
    return [tuple(part) for part in parts]


def _match_in(entry, cands):
    """Các dòng đơn trong `cands` ứng với 1 dòng chứng từ, theo thứ tự ưu tiên: đúng mã hàng →
    đúng tên hàng (mã đã đổi: sản phẩm cũ bị lưu trữ/xóa mã, dòng đơn cũ vẫn trỏ sản phẩm cũ) →
    dòng combo chứa mã con này. Trả (list dòng, 'code'|'name'|'component'), không có trả ([], None)."""
    direct = [cand for cand in cands if cand['code'] and cand['code'] == entry['item_code']]
    if direct:
        return direct, 'code'
    name = name_key(entry['description'])
    by_name = [cand for cand in cands if name and cand['name'] == name]
    if by_name:
        return by_name, 'name'
    kit = [cand for cand in cands if entry['item_code'] and entry['item_code'] in cand['component_codes']]
    return (kit[:1], 'component') if kit else ([], None)


def allocate_entries(entries, candidates_by_order, invoice_candidates):
    """Chia các dòng chứng từ MISA về đúng dòng đơn bán Odoo.

    Mỗi candidate: {'sale_line_id', 'code', 'name', 'component_codes', 'capacity'} — code/name là
    mã/tên hàng của dòng đơn (đã chuẩn hóa), component_codes là mã sản phẩm con khi dòng đó là
    combo/kit (MISA rã combo ra từng mã con khi lập hóa đơn), capacity là số lượng đã giao.
      - candidates_by_order: {mã đơn: [candidate]} — các đơn được ghi trên dòng chứng từ.
      - invoice_candidates: [candidate] — các dòng đơn đã xuất qua những phiếu mang số hóa đơn
        này. Dùng khi dòng chứng từ KHÔNG ghi mã đơn (kế toán lập chứng từ thường bỏ trống cột
        này) hoặc ghi mã đơn mà đơn đó không có dòng hàng khớp (ghi nhầm mã đơn).

    1 đơn có nhiều dòng cùng hàng: rót theo sức chứa, tiền chia theo số lượng. Khớp qua mã con
    combo thì gắn nguyên dòng vào dòng combo, giữ số lượng mã con (không quy đổi được về số combo).

    Trả (allocations, unmatched): allocations là entry kèm 'sale_line_id', 'match_scope'
    ('order' | 'invoice'), 'match_by' ('code' | 'name' | 'component'); unmatched là các entry
    không gắn được dòng đơn nào.
    """
    remaining = {}
    for cand in [c for cands in candidates_by_order.values() for c in cands] + list(invoice_candidates):
        remaining[cand['sale_line_id']] = max(cand['capacity'] or 0.0, 0.0)
    allocations, unmatched = [], []
    for entry in entries:
        scope = 'order'
        matched, match_by = _match_in(entry, candidates_by_order.get(entry['order_code']) or [])
        if not matched:
            scope = 'invoice'
            matched, match_by = _match_in(entry, invoice_candidates)
        if not matched:
            unmatched.append(entry)
            continue
        if match_by == 'component':
            allocations.append(dict(entry, sale_line_id=matched[0]['sale_line_id'], match_scope=scope, match_by=match_by))
            continue
        # Số lượng 0/âm (dòng điều chỉnh) không rót theo sức chứa được — gắn cả vào dòng đầu.
        parts = (
            _fill_by_capacity(entry['quantity'], matched, remaining) if entry['quantity'] > 0
            else [(matched[0], entry['quantity'])]
        )
        amounts = split_by_weights(entry['amount'], [qty for _cand, qty in parts])
        for (cand, qty), amount in zip(parts, amounts):
            allocations.append(dict(
                entry, sale_line_id=cand['sale_line_id'], quantity=qty, amount=amount,
                match_scope=scope, match_by=match_by,
            ))
    return allocations, unmatched


def line_payment_state(entries, tolerance):
    """Tình trạng thu tiền của 1 dòng đơn bán từ các phần chứng từ MISA đã gắn vào nó.

    Nhận: entries — list dict có 'amount', 'paid_state'; tolerance — sai số tiền chấp nhận.
    Trả 'none' (chưa có trên chứng từ MISA nào), 'paid', 'partial' (có phần đã thu, có phần
    chưa), 'unpaid', hoặc 'unknown' (có phần MISA trả paid_type lạ mà chưa thu đủ — không đoán).
    """
    if not entries:
        return 'none'
    total = sum(e['amount'] for e in entries)
    paid = sum(e['amount'] for e in entries if e['paid_state'] == 'paid')
    if total - paid <= tolerance:
        return 'paid'
    if any(e['paid_state'] == 'unknown' for e in entries):
        return 'unknown'
    return 'partial' if paid > tolerance else 'unpaid'


def overdue_days(due_date, today):
    """Số ngày quá hạn: dương = đã quá hạn, 0 = đến hạn hôm nay, âm = còn bấy nhiêu ngày.

    Nhận 2 date. due_date rỗng (MISA không ghi ngày hóa đơn) trả 0 — coi như đến hạn, để vẫn
    hiện trong danh sách cần đòi chứ không bị chìm.
    """
    if not due_date:
        return 0
    return (today - due_date).days


def status_label(days):
    """Nhãn trạng thái giống sheet công nợ: "Quá hạn N ngày" / "Đến hạn hôm nay" / "Còn N ngày".

    Nhận int (kết quả overdue_days). Trả str.
    """
    if days > 0:
        return 'Quá hạn %s ngày' % days
    if days == 0:
        return 'Đến hạn hôm nay'
    return 'Còn %s ngày' % -days


def aging_bucket_of(days):
    """Khóa nhóm tuổi nợ (AGING_BUCKETS) ứng với số ngày quá hạn. Nhận int, trả str."""
    for key, _label, low, high in AGING_BUCKETS:
        if (low is None or days >= low) and (high is None or days <= high):
            return key
    return AGING_BUCKETS[-1][0]


def in_bucket(days, bucket):
    """Số ngày quá hạn này có thuộc bộ lọc nhóm `bucket` không. 'overdue' = mọi mức quá hạn
    (>= 1 ngày); rỗng = không lọc (luôn True). Nhận int + str, trả bool."""
    if not bucket:
        return True
    if bucket == 'overdue':
        return days > 0
    return aging_bucket_of(days) == bucket


def summarize_receivables(rows):
    """Tổng công nợ + chia theo nhóm tuổi nợ cho các ô số liệu đầu tab.

    rows: list dict có 'amount' và 'overdue_days'. Trả dict:
    {'total_amount', 'total_count', 'overdue_amount', 'overdue_count',
     'buckets': [{'key', 'label', 'amount', 'count'}, ...]} — đủ mọi nhóm theo thứ tự
    AGING_BUCKETS, nhóm không có hóa đơn nào vẫn có mặt với 0. rows rỗng trả toàn 0.
    """
    by_key = {key: {'key': key, 'label': label, 'amount': 0.0, 'count': 0} for key, label, _l, _h in AGING_BUCKETS}
    overdue_amount, overdue_count, total_amount = 0.0, 0, 0.0
    for row in rows or []:
        bucket = by_key[aging_bucket_of(row['overdue_days'])]
        bucket['amount'] += row['amount']
        bucket['count'] += 1
        total_amount += row['amount']
        if row['overdue_days'] > 0:
            overdue_amount += row['amount']
            overdue_count += 1
    return {
        'total_amount': total_amount,
        'total_count': len(rows or []),
        'overdue_amount': overdue_amount,
        'overdue_count': overdue_count,
        'buckets': [by_key[key] for key, _label, _l, _h in AGING_BUCKETS],
    }
