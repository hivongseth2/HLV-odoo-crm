# -*- coding: utf-8 -*-
"""DỰ TRÙ — CHƯA CHẠY. Chuyển phiếu chuyển kho chưa hoàn tất từ "Inter-warehouse transit" sang CHUYENKHO.

Chạy trong odoo shell (thử trên staging trước):
    odoo-bin shell -d <db> < custom_addons/deltatech_picking_transit/scripts/migrate_transit_to_chuyenkho.py

Mặc định DRY_RUN = True: chỉ in ra sẽ làm gì, rollback cuối script. Đặt False để ghi thật.

A. Bước 1 chưa xong (Tồn kho → Transit): đổi đích phiếu/move/move line sang CHUYENKHO của kho nguồn.
B. Bước 2 chưa xong (Transit → kho nhận), hàng đang nằm ở Transit:
   1. bỏ giữ hàng phiếu bước 2;
   2. tạo move Transit → CHUYENKHO kho nguồn (đúng lô/kiện đang có ở Transit) và xác nhận;
   3. đổi header đích phiếu bước 1 (đã xong) sang CHUYENKHO — bắt buộc, vì stock.picking.read()
      tự sửa nguồn bước 2 về đúng đích bước 1;
   4. đổi nguồn phiếu bước 2 sang CHUYENKHO và giữ hàng lại.
   Không đủ hàng ở Transit → bỏ qua phiếu đó (không chuyển dở dang), in ra để xử lý tay.
C. In tồn còn sót ở Transit để kiểm tra.
"""
DRY_RUN = True

Picking = env["stock.picking"]
Move = env["stock.move"]
Quant = env["stock.quant"]

transit_locs = env["stock.location"].search([("usage", "=", "transit")]).filtered(Picking._is_inter_warehouse_transit)
print("Transit cũ:", transit_locs.mapped("complete_name"))
open_states = ("draft", "waiting", "confirmed", "assigned")
report = {"step1": [], "step2": [], "skip": []}


def hub_of(warehouse):
    return warehouse._hlv_get_transfer_location() if warehouse else False


# ---------- A. Bước 1 ----------
for picking in Picking.search([("state", "in", open_states), ("location_dest_id", "in", transit_locs.ids)]):
    hub = hub_of(picking.picking_type_id.warehouse_id or picking.location_id.warehouse_id)
    if not hub:
        report["skip"].append((picking.name, "bước 1: không xác định được kho nguồn"))
        continue
    report["step1"].append((picking.name, hub.complete_name))
    if not DRY_RUN:
        picking.write({"location_dest_id": hub.id})  # picking.write tự ghi xuống move
        picking.move_line_ids.filtered(lambda l: l.location_dest_id in transit_locs).write({"location_dest_id": hub.id})

# ---------- B. Bước 2 ----------
for picking in Picking.search([("state", "in", open_states), ("location_id", "in", transit_locs.ids)]):
    src = picking.source_transfer_id
    hub = hub_of(src and (src.picking_type_id.warehouse_id or src.location_id.warehouse_id))
    if not hub:
        report["skip"].append((picking.name, "bước 2: không có phiếu bước 1 (source_transfer_id) để biết kho nguồn"))
        continue
    transit = picking.location_id

    # Kiểm đủ hàng ở Transit trước khi đụng vào gì (không giữ của phiếu này vì sắp bỏ giữ)
    short = []
    for move in picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel")):
        quants = Quant.search([("product_id", "=", move.product_id.id), ("location_id", "child_of", transit.id)])
        free = sum(quants.mapped("quantity")) - sum(quants.mapped("reserved_quantity")) \
            + sum(move.move_line_ids.mapped("quantity_product_uom"))
        if free < move.product_qty - 1e-6:
            short.append("%s cần %s, Transit trống %s" % (move.product_id.display_name, move.product_qty, free))
    if short:
        report["skip"].append((picking.name, "thiếu hàng ở Transit: " + "; ".join(short)))
        continue
    report["step2"].append((picking.name, src.name, hub.complete_name))
    if DRY_RUN:
        continue

    picking.do_unreserve()
    moves = Move.create([{
        "name": "CHUYENKHO migrate %s" % picking.name,
        "origin": picking.name,
        "product_id": m.product_id.id,
        "product_uom": m.product_uom.id,
        "product_uom_qty": m.product_uom_qty,
        "location_id": transit.id,
        "location_dest_id": hub.id,
        "company_id": picking.company_id.id,
    } for m in picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))])
    moves._action_confirm()
    moves._action_assign()
    if any(m.state != "assigned" for m in moves):
        raise Exception("%s: không giữ đủ hàng ở Transit, dừng (rollback toàn bộ)" % picking.name)
    for ml in moves.move_line_ids:
        # ponytail: giữ nguyên kiện khi chuyển; kiện bị chia giữa 2 phiếu sẽ lỗi → xử lý tay nếu gặp
        ml.write({"location_dest_id": hub.id, "result_package_id": ml.package_id.id, "picked": True})
    moves._action_done()

    # SQL chỉ sửa header phiếu bước 1 đã xong: ORM write sẽ ghi lan xuống move/move line đã done (lịch sử)
    env.cr.execute("UPDATE stock_picking SET location_dest_id = %s WHERE id = %s", (hub.id, src.id))
    src.invalidate_recordset(["location_dest_id"])
    picking.write({"location_id": hub.id})
    picking.move_line_ids.write({"location_id": hub.id})
    picking.action_assign()

# ---------- Báo cáo ----------
print("\nA. Bước 1 đổi đích (%s):" % len(report["step1"]))
for row in report["step1"]:
    print("  %s → %s" % row)
print("\nB. Bước 2 đổi nguồn (%s):" % len(report["step2"]))
for row in report["step2"]:
    print("  %s (bước 1 %s) ← %s" % row)
print("\nBỏ qua (%s):" % len(report["skip"]))
for row in report["skip"]:
    print("  %s: %s" % row)
print("\nC. Tồn còn ở Transit:")
for q in Quant.search([("location_id", "child_of", transit_locs.ids), ("quantity", "!=", 0)]):
    print("  %s | %s | lô %s | kiện %s | %s" % (q.location_id.complete_name, q.product_id.display_name,
                                              q.lot_id.name or "-", q.package_id.name or "-", q.quantity))

if DRY_RUN:
    env.cr.rollback()
    print("\nDRY_RUN: đã rollback, chưa ghi gì.")
else:
    env.cr.commit()
    print("\nĐã commit.")
