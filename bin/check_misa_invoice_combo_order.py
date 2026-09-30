# -*- coding: utf-8 -*-
"""
check_misa_invoice_combo_order.py
=================================
Đơn có COMBO (dòng cha giá cả combo + các dòng con giao hàng) mà phiếu xuất kho ghi tiền xuất
kho = 0 trong khi MISA đã xuất HĐ đủ — khung "Vì sao còn lệch" báo "HĐ nhiều hơn xuất kho".
Case thật: DH125524949234781 / KBC/OUT/11613 — combo CB-M18ONEFHIWF1... 16.297.200 đ đã giao 0,
3 dòng con (máy siết, pin, sạc) đã giao đủ; phiếu XK = 0 đ, đề nghị DN0017572 HĐ 00004383 đủ
16.297.200 đ.

Giả thuyết cần kiểm: tiền xuất kho của phiếu (field Studio x_studio_tng_tin_sau_thu, chụp lúc
xác nhận xuất kho) cộng theo GIÁ DÒNG ĐƠN BÁN của từng move — move của dòng con giá 0 (tiền nằm
ở dòng cha, dòng cha không có move vì không giao hàng) → phiếu ra 0.

Script in ra:
  A. Định nghĩa field Studio x_studio_tng_tin_sau_thu (compute/depends/store) — biết nó tính gì.
  B. Từng dòng đơn bán: sản phẩm, loại, liên kết cha–con combo (nếu có field), SL đặt/giao,
     đơn giá, thành tiền trước/sau thuế.
  C. Từng phiếu của đơn: loại phiếu, trạng thái, tiền Studio, tiền thực xuất ròng, hàng trả,
     tiền HĐ quy về; từng move: sản phẩm, SL, dòng đơn bán gắn với move + giá dòng đó.
  D. MISA: mọi đề nghị nhắc tới mã đơn, dòng hàng (mã, SL, tiền) — MISA rã combo thế nào.

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_combo_order.py
"""

ORDER_NAMES = ['DH125524949234781']
STUDIO_FIELD = 'x_studio_tng_tin_sau_thu'
# Field liên kết dòng cha–con combo có thể có trên sale.order.line (Odoo 18 chuẩn + Studio/module
# riêng) — in field nào tồn tại.
LINE_LINK_FIELDS = ('combo_item_id', 'linked_line_id', 'linked_line_ids', 'is_combo', 'x_studio_combo', 'display_type')

SEP = "=" * 100
SUB = "-" * 100

SaleOrder = env['sale.order'].sudo().with_context(active_test=False)
Picking = env['stock.picking'].sudo()
misa = env['misa.api.utils'].sudo()


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def val(rec, name):
    if name not in rec._fields:
        return None
    value = rec[name]
    if hasattr(value, '_name'):
        return value.display_name if len(value) <= 1 else ', '.join(value.mapped('display_name'))
    return value


print(f"\n{SEP}\n  A. FIELD STUDIO {STUDIO_FIELD} trên stock.picking\n{SEP}")
field = env['ir.model.fields'].sudo().search([('model', '=', 'stock.picking'), ('name', '=', STUDIO_FIELD)], limit=1)
if not field:
    print("  (không có field này)")
else:
    print(f"  ttype={field.ttype} store={field.store} readonly={field.readonly} related={field.related or '-'}")
    print(f"  depends={field.depends or '-'}")
    print("  compute:")
    for line in (field.compute or '(không có — ghi tay / automation)').splitlines():
        print(f"      {line}")
    automations = env['base.automation'].sudo().search([('model_id.model', '=', 'stock.picking')]) \
        if 'base.automation' in env else env['ir.model'].browse()
    for auto in automations:
        code = getattr(auto, 'code', '') or ' '.join(auto.action_server_ids.mapped('code') or [])
        if STUDIO_FIELD in (code or ''):
            print(f"\n  Automation '{auto.name}' (trigger={getattr(auto, 'trigger', '?')}) có ghi field này:")
            for line in code.splitlines():
                print(f"      {line}")

for order_name in ORDER_NAMES:
    order = SaleOrder.search([('name', '=', order_name)], limit=1)
    print(f"\n{SEP}\n  ĐƠN {order_name}\n{SEP}")
    if not order:
        print("  Không tìm thấy đơn.")
        continue
    print(f"  {order.partner_id.display_name} | trước thuế {money(order.amount_untaxed)} | VAT {money(order.amount_tax)}"
          f" | tổng {money(order.amount_total)}")

    print(f"\n{SUB}\n  B. DÒNG ĐƠN BÁN\n{SUB}")
    for line in order.order_line:
        links = {name: val(line, name) for name in LINE_LINK_FIELDS if name in line._fields and val(line, name)}
        product = line.product_id
        print(f"    #{line.id} [{product.default_code or '-'}] {product.name or line.name!r}"
              f"\n        loại={product.type} bom={'có' if 'bom_ids' in product._fields and product.bom_ids else 'không'}"
              f" SL đặt={line.product_uom_qty} đã giao={line.qty_delivered}"
              f" đơn giá={money(line.price_unit)} trước thuế={money(line.price_subtotal)} sau thuế={money(line.price_total)}"
              f"{' | ' + str(links) if links else ''}")

    print(f"\n{SUB}\n  C. PHIẾU KHO CỦA ĐƠN\n{SUB}")
    for picking in order.picking_ids.sorted('id'):
        print(f"    {picking.name:<16} loại={picking.picking_type_id.code} trạng thái={picking.state}"
              f" {STUDIO_FIELD}={money(val(picking, STUDIO_FIELD))}"
              f" | thực xuất ròng={money(val(picking, 'misa_invoice_net_actual_amount'))}"
              f" trả={money(val(picking, 'misa_invoice_returned_amount'))}"
              f" HĐ quy về={money(val(picking, 'misa_invoice_allocated_amount'))}"
              f" HĐ={val(picking, 'misa_invoice_state')}")
        for move in picking.move_ids:
            sl = move.sale_line_id
            print(f"        move [{move.product_id.default_code or '-'}] SL={move.quantity}/{move.product_uom_qty}"
                  f" → dòng đơn #{sl.id or '-'} [{sl.product_id.default_code or '-'}]"
                  f" giá dòng sau thuế/1={money(sl.price_total / sl.product_uom_qty if sl and sl.product_uom_qty else 0)}")

    print(f"\n{SUB}\n  D. MISA — đề nghị nhắc tới {order_name}\n{SUB}")
    try:
        requests = misa.get_invoice_requests_for_order(order_name)
    except Exception as e:
        print(f"  ❌ Lỗi gọi MISA: {e}")
        requests = []
    for req in requests:
        print(f"    đề nghị {req['refno']} HĐ {req['inv_no'] or '(chưa phát hành)'}")
        for line in misa.get_invoice_request_lines(req['refid']):
            mark = '' if (line.get('order_code') or '').strip() == order_name else '   (đơn khác)'
            print(f"        {line.get('order_code')} {line.get('inventory_item_code')!r} SL={line.get('quantity')}"
                  f" tiền={money(line.get('amount_oc'))} VAT={money(line.get('vat_amount_oc'))}{mark}")

print(f"\n{SEP}")
print("  Đọc kết quả: nếu mục C cho thấy move chỉ trỏ vào dòng CON (giá 0) và dòng cha (giá cả combo)\n"
      "  không có move nào, còn mục A cộng theo giá dòng đơn của move → tiền xuất kho 0 là do cách tính\n"
      "  field Studio với combo, không phải chưa xuất HĐ.")
print(SEP)
