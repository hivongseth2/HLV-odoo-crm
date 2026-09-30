# -*- coding: utf-8 -*-
"""
fix_misa_invoice_unnumbered_invoiced.py
=======================================
Kiểm tra lại với MISA các phiếu đang "Đã xuất HĐ" mà KHÔNG có số hóa đơn.

Nguyên nhân (đã sửa trong misa_api_utils_ext._misa_invoice_result_from_request_by_customer):
MISA bỏ hẳn cột inv_no ở đề nghị CHƯA phát hành, nên đề nghị chưa phát hành rơi vào đường dự
phòng tìm hóa đơn theo tên khách — và hóa đơn NHÁP (chưa có số) trỏ về đề nghị bị coi là đã
xuất HĐ. Case thật KBC/OUT/13489 (DH125524949235029): đề nghị KBC/OUT/13489 chưa phát hành, phiếu
báo đã xuất HĐ 8.726.400 đ với số HĐ trống.

Soát mẫu 30/09/2026 (bin/check_misa_invoice_unnumbered_invoiced.py) trên 461 phiếu thấy 2 nhóm:
  - Đề nghị ĐÃ phát hành từ sau (KBC/OUT/13249, 12537...): lần kiểm tra đầu hóa đơn còn nháp nên
    ghi "Đã xuất HĐ" không số, cron không kiểm lại phiếu đã xuất HĐ nên số trống mãi. Kiểm tra lại
    → đi đường chính, ĐIỀN số HĐ, vẫn "Đã xuất HĐ".
  - Đề nghị VẪN chưa phát hành, hóa đơn nháp (KBC/OUT/13489, 13577, TSN/OUT/14807...): kiểm tra lại
    → về "Đã đề nghị, chờ HĐ", hết tính tiền HĐ chưa có.

Chỉ lấy phiếu TỰ có đề nghị (không ăn theo phiếu khác) và không có lượt khớp HĐ hải quan — phiếu
hải quan luôn mang số HĐ của dòng hải quan. Chạy thật = action_check_misa_invoice_status từng
phiếu (hỏi lại MISA).

DRY_RUN = True (mặc định): chỉ liệt kê. Đặt False để kiểm tra lại thật (gọi MISA, tự commit).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server), SAU KHI đã deploy bản sửa:
    python odoo-bin shell -d <TEN_DATABASE> < bin/fix_misa_invoice_unnumbered_invoiced.py
"""

import inspect

DRY_RUN = True
SEP = "=" * 100

Picking = env['stock.picking'].sudo()
fallback = type(env['misa.api.utils'])._misa_invoice_result_from_request_by_customer
if 'hóa đơn nháp' not in inspect.getsource(fallback):
    raise SystemExit("❌ Server chưa có bản sửa hóa đơn nháp — deploy trước, không thì kiểm tra lại vẫn ra 'Đã xuất HĐ'.")


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


customs_picking_ids = set(env['misa.invoice.customs.match'].sudo().search([]).mapped('picking_id').ids)
pickings = Picking.search([
    ('misa_invoice_state', '=', 'invoiced'),
    ('misa_invoice_master_picking_id', '=', False),
    ('misa_invoice_request_refid', '!=', False),
    '|', ('misa_invoice_no', '=', False), ('misa_invoice_no', '=', ''),
]).filtered(lambda p: p.id not in customs_picking_ids)

print(f"\n{SEP}\n  PHIẾU 'ĐÃ XUẤT HĐ' KHÔNG CÓ SỐ HĐ — {'CHẠY THỬ' if DRY_RUN else 'KIỂM TRA LẠI THẬT'}: {len(pickings)} phiếu\n{SEP}")
for picking in pickings.sorted('date_done'):
    orders = ', '.join(picking.misa_invoice_sale_order_ids.mapped('name'))
    line = (f"  {picking.name:<16} {str(picking.date_done)[:10]} {orders:<22} XK {money(picking.misa_invoice_net_actual_amount):>13}"
            f" | tiền HĐ đang ghi {money(picking.misa_invoice_amount):>13} | đề nghị {picking.misa_invoice_request_refno or '-'}")
    if DRY_RUN:
        print(line)
        continue
    try:
        picking.action_check_misa_invoice_status()
        env.cr.commit()
        print(f"{line} → {picking.misa_invoice_state}")
    except Exception as e:
        env.cr.rollback()
        print(f"{line} → ❌ {e}")

print(SEP)
print("  CHẠY THỬ — chưa gọi MISA, chưa ghi gì. Đặt DRY_RUN = False rồi chạy lại." if DRY_RUN else "  XONG.")
print(SEP)
