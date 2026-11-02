# -*- coding: utf-8 -*-
"""
check_shipper_photo_not_validated.py
====================================
Truy vì sao shipper ĐÃ chụp ảnh phiếu giao hàng (trang /barcode/shipper) mà phiếu OUT
vẫn chưa "Hoàn tất".

Chạy (Odoo.sh: dán vào notebook Odoo-shell, hoặc):
    python odoo-bin shell -d <DB> < bin/check_shipper_photo_not_validated.py

Luồng trên điện thoại (hlv_barcode_shipper/static/src/js/barcode_scanner.js):
    chụp ảnh → POST /api/barcode/upload_delivery_photo   (ghi chatter + scan log "gửi ảnh")
             → confirm("Xác nhận hoàn tất N đơn hàng?")   (bấm Hủy là dừng, KHÔNG để lại dấu vết)
             → POST /api/barcode/complete_out → button_validate() với sudo
                 thành công : scan log "Đơn hàng X đã hoàn tất"
                 lỗi        : chỉ hiện trên màn hình + log server, KHÔNG ghi scan log
Vì vậy: có log "gửi ảnh" mà không có log "đã hoàn tất" → complete_out không được gọi hoặc đã lỗi.
Có log "đã hoàn tất" mà phiếu chưa done → button_validate trả về wizard (VD backorder) mà
controller vẫn coi là thành công.

Từ hlv_barcode_shipper 18.0.3.14.0: hỏi xác nhận (hộp trong trang) TRƯỚC khi gửi ảnh, và
complete_out ghi scan log status=error khi lỗi hoặc phiếu không lên done — lỗi mới sẽ hiện ở mục C.
Case KBC/OUT/14830 (02/11/2026): log server có upload_delivery_photo 07:12 UTC nhưng không có
complete_out tới 07:50 → hộp confirm() bị Hủy / tự đóng.

Mục E chạy THỬ button_validate đúng như controller (user shipper + sudo) trong savepoint rồi
rollback. _action_done bị chặn bằng ngoại lệ riêng ngay khi tới nơi, nên các việc gửi ra ngoài
chạy SAU khi done (Zalo ZNS, MISA CRM, AMIS) không bao giờ chạy.
"""
from datetime import timedelta

PICKING_NAME = "KBC/OUT/14830"   # <-- đổi nếu cần
SIBLING_WINDOW_MIN = 15          # tìm các phiếu khác shipper gửi ảnh cùng lượt (± phút)

VN = timedelta(hours=7)
SEP = "=" * 78


def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")


def vn(dt):
    return (dt + VN).strftime("%d/%m %H:%M:%S") if dt else "-"


Picking = env["stock.picking"].sudo()
Log = env["barcode.scan.log"].sudo()
picking = Picking.search([("name", "=", PICKING_NAME)], limit=1)
if not picking:
    raise SystemExit(f"Không tìm thấy phiếu {PICKING_NAME}")

# ── A. Phiếu ───────────────────────────────────────────────────────────────
section(f"A. PHIẾU {picking.name} (id={picking.id})")
sale = picking.sale_id
print(f"  state           : {picking.state}   type={picking.picking_type_id.display_name} "
      f"(code={picking.picking_type_id.code})")
print(f"  partner         : {picking.partner_id.display_name}")
print(f"  sale            : {sale.name or '-'}   misa_sale_edit_locked="
      f"{getattr(sale, 'misa_sale_edit_locked', 'N/A') if sale else '-'}")
print(f"  hold picking    : {getattr(picking, 'is_stock_hold_picking', 'N/A')}")
print(f"  shipper_scanned : {picking.shipper_scanned}  user={picking.shipper_user_id.name or '-'} "
      f"lúc {vn(picking.shipper_scan_time)}")
print(f"  shipper_received: {picking.shipper_received}  by={picking.shipper_received_by.name or '-'} "
      f"lúc {vn(picking.shipper_receive_time)}")
print(f"  shipper_returned: {picking.shipper_returned}  lý do={picking.shipper_return_reason or '-'}")
print(f"  date_done       : {vn(picking.date_done)}")
print(f"  write_date      : {vn(picking.write_date)}  bởi {picking.write_uid.name}")
print("  Dòng hàng (demand / quantity / picked / state):")
for m in picking.move_ids:
    flag = "" if m.quantity >= m.product_uom_qty else "   <-- THIẾU (sẽ hỏi backorder)"
    print(f"    {m.product_id.default_code or m.product_id.name:<28} {m.product_uom_qty:>6} / "
          f"{m.quantity:>6} / {m.picked!s:<5} / {m.state}{flag}")

# ── B. Ảnh trong chatter ───────────────────────────────────────────────────
section("B. ẢNH SHIPPER TRONG CHATTER")
photo_msgs = env["mail.message"].sudo().search([
    ("model", "=", "stock.picking"), ("res_id", "=", picking.id),
    ("body", "ilike", "chụp ảnh phiếu giao hàng"),
], order="date asc")
for msg in photo_msgs:
    print(f"  {vn(msg.date)}  tác giả={msg.author_id.name}  uid={msg.create_uid.login}  "
          f"ảnh={len(msg.attachment_ids)}")
if not photo_msgs:
    print("  (không có ảnh shipper)")
photo_uid = photo_msgs[:1].create_uid
first_photo = photo_msgs[:1].date

# ── C. Scan log của phiếu ──────────────────────────────────────────────────
section("C. SCAN LOG CỦA PHIẾU (barcode.scan.log)")
logs = Log.search([("picking_id", "=", picking.id)], order="scan_time asc")
for lg in logs:
    print(f"  {vn(lg.scan_time)}  {lg.scan_type:<8} {lg.status:<7} {lg.user_id.login:<25} "
          f"{(lg.message or '')[:70]}")
if not logs:
    print("  (không có)")
done_logs = logs.filtered(lambda l: "đã hoàn tất" in (l.message or ""))

# ── D. Các phiếu khác cùng lượt gửi ảnh ────────────────────────────────────
section(f"D. PHIẾU KHÁC CÙNG USER GỬI ẢNH ±{SIBLING_WINDOW_MIN} PHÚT")
if photo_uid and first_photo:
    win = timedelta(minutes=SIBLING_WINDOW_MIN)
    siblings = Log.search([
        ("user_id", "=", photo_uid.id),
        ("scan_time", ">=", first_photo - win), ("scan_time", "<=", first_photo + win),
    ], order="scan_time asc")
    for lg in siblings:
        print(f"  {vn(lg.scan_time)}  {lg.barcode:<18} {lg.scan_type:<8} {lg.status:<7} "
              f"phiếu={lg.picking_id.state or '-':<9} {(lg.message or '')[:55]}")
    errors = Log.search([
        ("user_id", "=", photo_uid.id), ("status", "!=", "success"),
        ("scan_time", ">=", first_photo - win), ("scan_time", "<=", first_photo + win),
    ])
    print(f"  → log lỗi/cảnh báo trong khoảng này: {len(errors)}")
    print(f"  → user {photo_uid.login}: group_shipper="
          f"{photo_uid.has_group('hlv_barcode_shipper.group_shipper')}, "
          f"shipper_name={photo_uid.shipper_name or '-'}")
else:
    print("  (không có ảnh nên không xác định được lượt)")

# ── D2. Các phiếu OUT cùng lượt quét (cùng ảnh/lần bấm hoàn tất) ───────────
# Lượt nhiều phiếu gọi complete_out MỘT lần cho cả nhóm: nếu phiếu kia lỗi giữa chừng làm
# hỏng transaction thì cả nhóm cùng không done và không còn log nào.
section("D2. CÁC PHIẾU OUT CÙNG LƯỢT QUÉT")
if photo_uid and first_photo:
    so_names = set(siblings.filtered(lambda l: l.scan_type == "pick").mapped("barcode"))
    group = Picking.search([
        ("picking_type_id.code", "=", "outgoing"),
        "|", ("origin", "in", list(so_names)), ("id", "in", siblings.mapped("picking_id").ids),
    ])
    for p in group:
        p_logs = Log.search([("picking_id", "=", p.id)], order="scan_time asc")
        print(f"  {p.name:<16} origin={p.origin or '-':<20} state={p.state:<9} "
              f"done={vn(p.date_done)}")
        for lg in p_logs:
            print(f"      {vn(lg.scan_time)}  {lg.scan_type:<8} {lg.status:<7} "
                  f"{lg.user_id.login:<25} {(lg.message or '')[:55]}")

# ── D3. Có gì đổi giữa lần gửi ảnh đầu và lúc done ─────────────────────────
# Lần đầu không done mà lần sau done → tìm thứ đã thay đổi ở giữa: khóa sửa đơn MISA
# (misa_sale_edit_locked chặn button_validate của OUT), tracking, tin nhắn trên đơn / phiếu.
section("D3. THAY ĐỔI TRÊN ĐƠN BÁN / PHIẾU GIỮA LẦN ẢNH ĐẦU VÀ LÚC DONE")
if photo_uid and first_photo:
    t_from = first_photo - timedelta(minutes=SIBLING_WINDOW_MIN)
    t_to = (max(group.mapped("date_done") or [first_photo])) + timedelta(minutes=5)
    print(f"  khoảng: {vn(t_from)} → {vn(t_to)} (giờ VN)")
    orders = group.mapped("sale_id")
    for so in orders:
        print(f"  {so.name}: misa_sale_edit_locked={getattr(so, 'misa_sale_edit_locked', 'N/A')} "
              f"locked_at={vn(getattr(so, 'misa_sale_edit_locked_at', False))}")
    if "misa.sale.sync.snapshot" in env:
        snaps = env["misa.sale.sync.snapshot"].sudo().search([
            ("sale_order_id", "in", orders.ids),
            ("fetched_at", ">=", t_from), ("fetched_at", "<=", t_to),
        ], order="fetched_at asc")
        for sn in snaps:
            print(f"  snapshot MISA {sn.sale_order_id.name} lúc {vn(sn.fetched_at)}")
    targets = [("sale.order", oid) for oid in orders.ids] + [("stock.picking", pid) for pid in group.ids]
    msg_domain = ["|"] * (len(targets) - 1)
    for model, rid in targets:
        msg_domain += ["&", ("model", "=", model), ("res_id", "=", rid)]
    msgs = env["mail.message"].sudo().search(
        msg_domain + [("date", ">=", t_from), ("date", "<=", t_to)], order="date asc",
    )
    for msg in msgs:
        rec = env[msg.model].browse(msg.res_id)
        body = " ".join((msg.body or "").striptags().split())[:90] if msg.body else ""
        print(f"  {vn(msg.date)}  {rec.display_name:<18} {msg.author_id.name or '-':<20} {body}")
        for tv in msg.tracking_value_ids:
            ftype = tv.field_id.ttype
            print(f"      ~ {tv.field_id.name}: {tv._format_display_value(ftype, new=False)[0]} → "
                  f"{tv._format_display_value(ftype, new=True)[0]}")

# ── E. Chạy thử button_validate như controller complete_out ────────────────
section("E. CHẠY THỬ button_validate (user shipper + sudo, rollback)")


class _ReachedActionDone(BaseException):
    """BaseException để không bị các `except Exception` trong override nuốt mất."""


registry_cls = env.registry["stock.picking"]
orig_action_done = registry_cls._action_done


def _stop_at_action_done(self, *args, **kwargs):
    raise _ReachedActionDone()


dry_result, dry_error = None, None
run_user = photo_uid or env.user
registry_cls._action_done = _stop_at_action_done
try:
    with env.cr.savepoint():
        dry_result = picking.with_user(run_user).sudo().button_validate()
        raise _ReachedActionDone()  # không tới _action_done vẫn rollback mọi thứ đã ghi
except _ReachedActionDone:
    if dry_result is None:
        dry_result = "REACHED_ACTION_DONE"
except Exception as e:  # lỗi UserError/ValidationError… mà shipper đã thấy trên màn hình
    dry_error = e
finally:
    registry_cls._action_done = orig_action_done
    env.invalidate_all()

print(f"  chạy với user   : {run_user.login}")
if dry_error is not None:
    print(f"  → RAISE {type(dry_error).__name__}: {dry_error}")
elif dry_result == "REACHED_ACTION_DONE":
    print("  → Qua hết các kiểm tra, tới _action_done: bây giờ xác nhận được bình thường.")
elif isinstance(dry_result, dict):
    print(f"  → TRẢ VỀ WIZARD res_model={dry_result.get('res_model')} name={dry_result.get('name')}")
    print("    controller coi là thành công nhưng phiếu KHÔNG done.")
else:
    print(f"  → Trả về {dry_result!r} mà không tới _action_done (override nào đó chặn im lặng).")

# ── F. Kết luận ────────────────────────────────────────────────────────────
section("F. KẾT LUẬN")
if picking.state == "done":
    print("  Phiếu đã done — không còn vấn đề.")
elif not photo_msgs:
    print("  Không có ảnh shipper trên phiếu — không thuộc case này.")
elif done_logs:
    print("  complete_out đã ghi 'đã hoàn tất' nhưng phiếu chưa done → button_validate trả về")
    print("  wizard/True mà không validate (xem mục E). Lỗi ở controller: coi mọi kết quả")
    print("  không-raise là thành công.")
elif dry_error is not None:
    print("  Có ảnh, không có log 'đã hoàn tất', và chạy thử thì RAISE → khả năng cao lúc")
    print("  shipper bấm hoàn tất cũng gặp đúng lỗi này (hiện trên màn hình, không lưu log).")
    print(f"  Lỗi: {dry_error}")
elif dry_result == "REACHED_ACTION_DONE":
    print("  Có ảnh, không có log 'đã hoàn tất', và bây giờ validate được → hoặc lúc đó lỗi tạm")
    print("  (lock/tồn kho đã thay đổi/mất mạng), hoặc shipper bấm HỦY ở hộp xác nhận sau khi")
    print("  gửi ảnh. Đối chiếu mục D: các phiếu cùng lượt có done không; tra log server Odoo.sh")
    print(f"  quanh {vn(first_photo)} (giờ VN) với 'Error validating picking {picking.name}'.")
else:
    print("  Xem mục E: validate trả về wizard/True — phiếu không thể done qua luồng shipper.")
