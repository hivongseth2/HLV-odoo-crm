# -*- coding: utf-8 -*-
"""
find_misa_customs_duplicate_numbers.py
======================================
Tìm các hóa đơn đã ghi nhận ở tab Đơn hải quan mà trên MISA được lập gộp cho NHIỀU chứng từ bán
hàng (mỗi chứng từ 1 refid, mang dòng hàng riêng) — bản module trước 1.13 chỉ đọc 1 chứng từ,
ghi nhận lại là xóa mất dòng của các chứng từ kia (case thật HĐ 00005319: mất 22/27 dòng,
134.995.000 đ của Coherent).

Với mỗi số hóa đơn đang có trong tab Đơn hải quan: hỏi MISA mọi chứng từ mang ĐÚNG số đó, so
với refid Odoo đang lưu. Hóa đơn nào có chứng từ mà Odoo KHÔNG có dòng nào → cần ghi nhận lại
số đó ở tab Đơn hải quan (bản 1.13 lưu đủ dòng của mọi chứng từ).

Lưu ý khi ghi nhận lại: các dòng cũ của số đó bị xóa và tạo lại, lượt khớp TAY trên các dòng
cũ phải khớp lại (lượt khớp tự động tự chạy lại).

CHỈ ĐỌC — không write/create/unlink gì. Mỗi số hóa đơn 1 lệnh gọi MISA.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/find_misa_customs_duplicate_numbers.py
"""

SEP = "=" * 100

misa = env['misa.api.utils'].sudo()
CustomsLine = env['misa.invoice.customs.line'].sudo()


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


inv_nos = sorted(set(CustomsLine.search([]).mapped('invoice_no')))
print(f"\n{SEP}\n  SOÁT {len(inv_nos)} SỐ HÓA ĐƠN Ở TAB ĐƠN HẢI QUAN VỚI MISA\n{SEP}")

need_resave = []
for inv_no in inv_nos:
    lines = CustomsLine.search([('invoice_no', '=', inv_no)])
    odoo_refids = set(lines.mapped('invoice_refid'))
    try:
        vouchers = misa._misa_invoice_vouchers_for_inv_no(inv_no)
    except Exception as e:
        print(f"  ❌ {inv_no}: lỗi gọi MISA: {type(e).__name__}: {e}")
        continue
    missing = [v for v in vouchers if v.get('refid') not in odoo_refids]
    if len(vouchers) <= 1 and not missing:
        continue
    manual = lines.mapped('match_ids').filtered('is_manual')
    print(f"\n  {inv_no}: hóa đơn gộp {len(vouchers)} chứng từ trên MISA, Odoo đang lưu {len(odoo_refids)} "
          f"({len(lines)} dòng, {len(manual)} lượt khớp tay sẽ phải khớp lại nếu ghi nhận lại)")
    for voucher in vouchers:
        state = 'ODOO THIẾU' if voucher in missing else 'đã có'
        print(f"      [{state:<10}] refid={voucher.get('refid')} lập {str(voucher.get('created_date'))[:10]}"
              f" {voucher.get('account_object_name')} tổng {money(voucher.get('total_amount'))} đ")
    if missing:
        need_resave.append(inv_no)

print(f"\n{SEP}")
if need_resave:
    print(f"  {len(need_resave)} số hóa đơn cần GHI NHẬN LẠI ở tab Đơn hải quan (sau khi deploy 1.13):")
    print("    " + ", ".join(need_resave))
else:
    print("  Không có hóa đơn nào đang thiếu dòng của chứng từ bán hàng.")
print(SEP)
