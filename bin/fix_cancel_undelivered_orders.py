# -*- coding: utf-8 -*-
"""
fix_cancel_undelivered_orders.py
================================
TRƯỜNG HỢP 1 — phiếu lấy hàng đã HUỶ mà đơn bán chưa huỷ: huỷ luôn đơn.

Case thật DH125524949232196: phiếu lấy hàng DH125524949232196 bị nhân viên kho huỷ 15/07 (đã rút 2 cái
48-22-8435 nhường cho đơn DH125524949232389), đơn vẫn "Đơn bán hàng" → báo cáo chưa giao / điều phối /
doanh thu vẫn đếm. Đơn Shopee cũng vậy: sàn "Đã hủy", phiếu đã huỷ, đơn Odoo còn treo.

Chọn đơn: "Đơn bán hàng", có phiếu, MỌI phiếu liên quan (nối đơn / cùng nhóm cung ứng / cùng chứng từ
gốc) đã huỷ, chưa giao gì. Đơn bị BỎ QUA (cần người xem) nếu:
  - đơn khoá; đơn Zalo Mini App (huỷ sẽ gửi callback ra Zalo — việc ra ngoài, làm tay);
  - có dòng Đã giao > 0, hoặc có move XONG thuộc đơn;
  - còn phiếu CHƯA huỷ liên quan đơn (vd PACK đã xong mà PICK huỷ);
  - có hoá đơn Odoo đã vào sổ; phiếu nào đã ghi nhận xuất HĐ MISA;
  - Shopee báo hàng đã đi (Đang giao / Giao lại / Đã nhận hàng / Hoàn thành / Đang trả hàng) mà phiếu
    Odoo huỷ hết — hàng có thể đi qua phiếu khác, soát tay;
  - phiếu huỷ chưa quá MIN_AGE_DAYS ngày (tránh đúng lúc đang huỷ để làm lại phiếu). Ngày huỷ lấy từ
    lịch sử trạng thái phiếu, KHÔNG lấy write_date — một đợt cập nhật hàng loạt 29/09/2026 đã chạm
    write_date của gần hết phiếu cũ.

Huỷ bằng action_cancel chuẩn (context disable_cancel_warning: không mở wizard, không gửi mail khách).

LƯU Ý: đơn MISA bị huỷ trên Odoo mà sau đó có ai "đồng bộ lại" đơn đó từ MISA (MISA chưa huỷ) thì
sale_order_misa_sync đưa đơn về NHÁP rồi đồng bộ lại. Đơn thật sự huỷ thì nên huỷ cả bên MISA.

ORDERS: đơn cần huỷ; để [] = quét mọi đơn "Đơn bán hàng" có phiếu mà phiếu nào cũng đã huỷ.
DRY_RUN = True (mặc định): làm thật trong transaction để in kết quả, rồi rollback hết. Đặt False để ghi.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/fix_cancel_undelivered_orders.py
"""

from collections import defaultdict
from datetime import timedelta

from odoo import fields

ORDERS = []
DRY_RUN = True
MIN_AGE_DAYS = 1
LIST_LIMIT = 300  # dòng in tối đa — shell cắt log dài
# Trạng thái Shopee nói hàng ĐÃ rời kho (mã tiếng Anh + tên Việt, theo shopee_webhook _STATUS_MAP).
SHOPEE_SENT = {
    'SHIPPED', 'Đang giao', 'RETRY_SHIP', 'Giao lại', 'TO_CONFIRM_RECEIVE', 'Đã nhận hàng',
    'COMPLETED', 'Hoàn thành', 'TO_RETURN', 'Đang trả hàng',
}
EPS = 0.001
SEP = "=" * 100

SaleOrder = env['sale.order'].sudo()
Picking = env['stock.picking'].sudo()


class Skip(Exception):
    """Bỏ qua đơn — kèm lý do."""


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def related_pickings(order):
    """Phiếu nối đơn (sale_id) + phiếu cùng nhóm cung ứng / chứng từ gốc dù đã mất liên kết."""
    domain = ['|', ('sale_id', '=', order.id), ('origin', '=', order.name)]
    if order.procurement_group_id:
        domain = ['|', ('group_id', '=', order.procurement_group_id.id)] + domain
    return Picking.search(domain)


def cancelled_at(picking):
    """Lúc phiếu đổi trạng thái lần cuối (= lúc huỷ, vì giờ đang huỷ) theo tracking; không có thì ngày tạo."""
    tracking = env['mail.tracking.value'].sudo().search([
        ('mail_message_id.model', '=', 'stock.picking'), ('mail_message_id.res_id', '=', picking.id),
        ('field_id.name', '=', 'state'),
    ], order='id desc', limit=1)
    return tracking.mail_message_id.date if tracking else picking.create_date


def check_order(order, cutoff):
    """Ném Skip nếu đơn không được tự huỷ; trả (phiếu, lúc huỷ phiếu gần nhất)."""
    if order.locked:
        raise Skip("đơn đang khoá")
    if 'x_zalo_order_id' in order._fields and order.x_zalo_order_id:
        raise Skip("đơn Zalo Mini App — huỷ sẽ gửi callback ra Zalo, làm tay")
    if order.order_line.filtered(lambda l: l.qty_delivered > EPS):
        raise Skip("có dòng Đã giao > 0")
    pickings = related_pickings(order)
    if not pickings:
        raise Skip("không có phiếu nào")
    live = pickings.filtered(lambda p: p.state != 'cancel')
    if live:
        raise Skip(f"còn phiếu chưa huỷ: {', '.join(f'{p.name}({p.state})' for p in live)}")
    done_moves = env['stock.move'].sudo().search_count([
        ('sale_line_id.order_id', '=', order.id), ('state', '=', 'done')])
    if done_moves:
        raise Skip(f"có {done_moves} move XONG thuộc đơn")
    if order.invoice_ids.filtered(lambda inv: inv.state == 'posted'):
        raise Skip("có hoá đơn Odoo đã vào sổ")
    if 'misa_invoice_state' in Picking._fields and pickings.filtered(lambda p: p.misa_invoice_state == 'invoiced'):
        raise Skip("có phiếu đã ghi nhận xuất HĐ MISA")
    status = (order.shopee_order_status or '').strip() if 'shopee_order_status' in order._fields else ''
    if status in SHOPEE_SENT:
        raise Skip(f"Shopee báo '{status}' mà phiếu Odoo huỷ hết — soát tay (hàng đi qua phiếu khác?)")
    last_cancel = max(cancelled_at(p) for p in pickings)
    if last_cancel > cutoff:
        raise Skip(f"phiếu mới huỷ {str(last_cancel)[:16]} (< {MIN_AGE_DAYS} ngày) — có thể đang làm lại")
    return pickings, last_cancel


def cancel_order(order, cutoff):
    try:
        with env.cr.savepoint():
            pickings, last_cancel = check_order(order, cutoff)
            order.with_context(disable_cancel_warning=True).action_cancel()
            if order.state != 'cancel':
                raise Skip(f"action_cancel xong mà đơn vẫn '{order.state}'")
    except Skip as skip:
        return 'BỎ QUA', str(skip)
    except Exception as error:  # noqa: BLE001 — lỗi gì cũng hoàn tác đơn này, báo ra rồi đi tiếp
        return 'LỖI', f"{error} — đã hoàn tác"
    return 'HUỶ', f"phiếu huỷ {str(last_cancel)[:10]}: {', '.join(pickings.mapped('name'))}"


if ORDERS:
    orders = SaleOrder.search([('name', 'in', ORDERS)])
else:
    env.cr.execute("""
        SELECT so.id
          FROM sale_order so
         WHERE so.state = 'sale'
           AND EXISTS (SELECT 1 FROM stock_picking sp WHERE sp.sale_id = so.id)
           AND NOT EXISTS (SELECT 1 FROM stock_picking sp WHERE sp.sale_id = so.id AND sp.state <> 'cancel')
    """)
    orders = SaleOrder.browse([r[0] for r in env.cr.fetchall()])
orders = orders.filtered(lambda o: o.state == 'sale').sorted('date_order')
cutoff = fields.Datetime.now() - timedelta(days=MIN_AGE_DAYS)

print(f"\n{SEP}\n  TH1 — PHIẾU ĐÃ HUỶ MÀ ĐƠN CHƯA HUỶ — {'CHẠY THỬ (rollback cuối)' if DRY_RUN else 'GHI THẬT'}: "
      f"{len(orders)} đơn\n{SEP}")
counts, amounts, printed = defaultdict(int), defaultdict(float), 0
for order in orders:
    status, note = cancel_order(order, cutoff)
    counts[status] += 1
    amounts[status] += order.amount_total
    # Log ngắn: in hết dòng BỎ QUA / LỖI, dòng HUỶ chỉ in khi còn chỗ.
    if status != 'HUỶ' or printed < LIST_LIMIT:
        printed += 1
        shopee = (getattr(order, 'shopee_order_status', '') or '')[:14]
        print(f"  [{status:<7}] {order.name:<22} {str(order.date_order)[:10]} {money(order.amount_total):>13} đ "
              f"{shopee:<14} {order.partner_id.display_name[:28]:<28} | {note}")
    if not DRY_RUN:
        env.cr.commit()

if DRY_RUN:
    env.cr.rollback()
print(f"\n{SEP}")
for status in sorted(counts):
    print(f"  {status:<7} {counts[status]:>5} đơn | {money(amounts[status]):>16} đ")
print("  CHẠY THỬ — đã rollback, chưa ghi gì. Đặt DRY_RUN = False rồi chạy lại." if DRY_RUN else "  XONG — đã commit.")
print(SEP)
