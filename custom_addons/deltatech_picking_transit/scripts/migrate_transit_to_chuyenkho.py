# -*- coding: utf-8 -*-
"""DỰ TRÙ — CHƯA CHẠY. Chuyển phiếu chuyển kho chưa hoàn tất từ "Inter-warehouse transit" sang CHUYENKHO.

Chạy trong odoo shell (thử trên staging trước):
    odoo-bin shell -d <db> < custom_addons/deltatech_picking_transit/scripts/migrate_transit_to_chuyenkho.py

DRY_RUN = True (mặc định): chạy thật từng phiếu trong savepoint rồi rollback savepoint đó → báo cáo đúng như
khi chạy thật nhưng không ghi gì. Đặt False để ghi.
Điều kiện: module deltatech_picking_transit đã có bản stock.picking.read() bỏ qua phiếu done/cancel
(nếu không, mở phiếu bước 2 đã xong sẽ bị ghi đè lịch sử nguồn Transit → CHUYENKHO).

Transit không thuộc kho nào: hàng ở đó không tính vào tồn kho nào, chỉ hiện là "Nhập CK" ở dự báo kho nhận.

A. Bước 1 chưa xong (Tồn kho → Transit): hàng vẫn ở kho nguồn. Chỉ đổi đích sang CHUYENKHO kho nguồn.
B. Bước 2 chưa xong (Transit → kho nhận), gom theo phiếu bước 1 (source_transfer_id, gồm cả backorder):
   1. Còn ở Transit của chuyến này = SL đã quét bước 1 (theo SP/lô/kiện) − SL các phiếu bước 2 đã xong;
      chỉ lấy tối đa bằng nhu cầu các phiếu bước 2 còn mở.
   2. Xóa dòng chi tiết bước 2 (nhả giữ hàng, kể cả dòng đã quét — do_unreserve không nhả dòng đã quét).
   3. Move Transit → CHUYENKHO kho nguồn của bước 1 đúng SP/lô/kiện ở bước 1. Transit không đủ → bỏ cả nhóm.
      → tồn kho nguồn TĂNG lại SL này (nằm ở CHUYENKHO, đơn bán không lấy được), Transit giảm.
   4. Sửa header đích phiếu bước 1 (đã xong) sang CHUYENKHO — vì read() tự đặt nguồn bước 2 = đích bước 1.
   5. Đổi nguồn bước 2 sang CHUYENKHO, gán lại đúng SL vừa chuyển vào từng move (giữ vị trí đích + trạng thái
      đã quét nếu dòng cũ cùng SP/lô/kiện). Không giữ thêm hàng khác ở CHUYENKHO.
   → dự báo kho nguồn không đổi (Tồn +X, Xuất CK −X); kho nhận không đổi (Nhập CK X).
C. Bước 1 đã xong nhưng chưa có phiếu bước 2: hàng nằm ở Transit, script không đụng, in ra.
D. Tồn còn sót ở Transit (kể cả âm): in ra để kiểm kê/chuyển tay.
"""
DRY_RUN = False  # staging test: ghi thật. Đặt lại True để chỉ xem báo cáo

Picking = env["stock.picking"]
Move = env["stock.move"]
MoveLine = env["stock.move.line"]
Quant = env["stock.quant"]

transit_locs = env["stock.location"].search([("usage", "=", "transit")]).filtered(Picking._is_inter_warehouse_transit)
transit_area = env["stock.location"].search([("id", "child_of", transit_locs.ids)])
print("Transit cũ:", transit_locs.mapped("complete_name"))
OPEN = ("draft", "waiting", "confirmed", "assigned")
report = {"step1": [], "step2": [], "skip": []}


class DryRun(Exception):
    pass


def run(name, fn, bucket):
    """Mỗi phiếu/nhóm một savepoint: lỗi chỉ rollback phần đó; DRY_RUN rollback sau khi chạy xong."""
    note = None
    try:
        with env.cr.savepoint():
            note = fn()
            if DRY_RUN:
                raise DryRun()
    except DryRun:
        pass
    except Exception as e:
        report["skip"].append((name, str(e)))
        return
    report[bucket].append((name, note))


def hub_of(warehouse):
    return warehouse._hlv_get_transfer_location() if warehouse else False


# ---------- A. Bước 1 ----------
def migrate_step1(picking):
    hub = hub_of(picking.picking_type_id.warehouse_id or picking.location_id.warehouse_id)
    if not hub:
        raise Exception("bước 1: không xác định được kho nguồn")
    picking.write({"location_dest_id": hub.id})  # picking.write tự ghi xuống move
    picking.move_line_ids.filtered(lambda l: l.location_dest_id in transit_area).write({"location_dest_id": hub.id})
    return "→ " + hub.complete_name


for picking in Picking.search([("state", "in", OPEN), ("location_dest_id", "in", transit_area.ids)]):
    run(picking.name, lambda p=picking: migrate_step1(p), "step1")


# ---------- B. Bước 2, gom theo phiếu bước 1 ----------
def qty_by_key(lines, pkg_field):
    res = {}
    for l in lines:
        k = (l.product_id.id, l.lot_id.id, l[pkg_field].id)
        res[k] = res.get(k, 0.0) + l.quantity_product_uom
    return res


def migrate_group(src, open_pickings):
    hub = hub_of(src.picking_type_id.warehouse_id or src.location_id.warehouse_id)
    if not hub:
        raise Exception("không xác định được kho nguồn của %s" % src.name)
    moves = open_pickings.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
    need = {}
    for m in moves:
        need[m.product_id.id] = need.get(m.product_id.id, 0.0) + m.product_qty

    # 1. Phần của chuyến này còn ở Transit
    shipped = qty_by_key(src.move_line_ids.filtered(lambda l: l.location_dest_id in transit_area), "result_package_id")
    done_step2 = Picking.search([("source_transfer_id", "=", src.id), ("state", "=", "done")])
    received = qty_by_key(done_step2.move_line_ids.filtered(lambda l: l.location_id in transit_area), "package_id")
    for (pid, lot, pkg), qty in received.items():
        # đúng SP/lô/kiện trước, dư thì trừ vào dòng khác cùng SP (bước 2 có thể ghi lô khác bước 1)
        for k in sorted(shipped, key=lambda k: k != (pid, lot, pkg)):
            if k[0] == pid and qty > 0:
                take = min(qty, shipped[k])
                shipped[k] -= take
                qty -= take
    plan, notes = [], []  # plan: [(product_id, lot_id, package_id, qty)]
    for (pid, lot, pkg), qty in sorted(shipped.items()):
        take = min(qty, need.get(pid, 0.0))
        if take > 1e-6:
            plan.append((pid, lot, pkg, take))
            need[pid] -= take
        if qty - take > 1e-6:
            notes.append("dư %s %s ở Transit (vượt nhu cầu bước 2)" % (qty - take, env["product.product"].browse(pid).display_name))
    for pid, qty in need.items():
        if qty > 1e-6:
            notes.append("bước 2 thiếu %s %s so với bước 1 đã quét" % (qty, env["product.product"].browse(pid).display_name))
    if not plan:
        raise Exception("bước 1 không còn hàng nào ở Transit cho các phiếu bước 2")

    # 2. Nhả giữ hàng bước 2
    old = {}
    for l in open_pickings.move_line_ids:
        old[(l.move_id.id, l.product_id.id, l.lot_id.id, l.package_id.id)] = (l.location_dest_id.id, l.picked)
    open_pickings.move_line_ids.unlink()

    # 3. Transit → CHUYENKHO đúng SP/lô/kiện của bước 1
    mig_moves = Move
    for pid in {p[0] for p in plan}:
        product = env["product.product"].browse(pid)
        mig = Move.create({
            "name": "CHUYENKHO migrate %s" % src.name, "origin": src.name, "product_id": pid,
            "product_uom": product.uom_id.id, "product_uom_qty": sum(p[3] for p in plan if p[0] == pid),
            "location_id": transit_locs[0].id, "location_dest_id": hub.id, "company_id": src.company_id.id,
        })
        mig._action_confirm()
        for _pid, lot, pkg, qty in (p for p in plan if p[0] == pid):
            for q in Quant.search([("product_id", "=", pid), ("location_id", "in", transit_area.ids),
                                   ("lot_id", "=", lot or False), ("package_id", "=", pkg or False)]):
                take = min(qty, q.quantity - q.reserved_quantity)
                if take <= 1e-6:
                    continue
                MoveLine.create({
                    "move_id": mig.id, "product_id": pid, "product_uom_id": product.uom_id.id, "quantity": take,
                    "lot_id": lot or False, "package_id": pkg or False, "result_package_id": pkg or False,
                    "location_id": q.location_id.id, "location_dest_id": hub.id, "picked": True,
                })
                qty -= take
            if qty > 1e-6:
                raise Exception("Transit không đủ %s %s (lô %s, kiện %s) như bước 1 đã quét" % (
                    qty, product.display_name, env["stock.lot"].browse(lot).name or "-",
                    env["stock.quant.package"].browse(pkg).name or "-"))
        mig_moves |= mig
    mig_moves._action_done()

    # 4. + 5. Đổi nguồn và gán lại vào bước 2
    # SQL chỉ sửa header phiếu bước 1 đã xong: ORM write sẽ ghi lan xuống move/move line đã done (lịch sử)
    env.cr.execute("UPDATE stock_picking SET location_dest_id = %s WHERE id = %s", (hub.id, src.id))
    src.invalidate_recordset(["location_dest_id"])
    open_pickings.write({"location_id": hub.id})
    plan = [list(p) + [p[3]] for p in plan]  # p[4] = SL ban đầu, để biết kiện có bị chia không
    for m in moves.sorted("id"):
        left = m.product_qty
        for p in (p for p in plan if p[0] == m.product_id.id and p[3] > 1e-6):
            take = min(left, p[3])
            if take <= 1e-6:
                break
            dest, picked = old.get((m.id, p[0], p[1], p[2]), (m.location_dest_id.id, False))
            MoveLine.create({
                "picking_id": m.picking_id.id, "move_id": m.id, "product_id": p[0],
                "product_uom_id": m.product_id.uom_id.id, "quantity": take, "lot_id": p[1] or False,
                "package_id": p[2] or False,
                # chia một kiện cho nhiều move thì không giữ kiện ở đích, tránh một kiện nằm hai nơi
                "result_package_id": (p[2] or False) if take == p[4] else False,
                "location_id": hub.id, "location_dest_id": dest, "picked": picked,
            })
            p[3] -= take
            left -= take
    moves._recompute_state()
    return "%s → %s | %s | %s" % (
        ", ".join(open_pickings.mapped("name")), hub.complete_name,
        "%s dòng chuyển" % len(mig_moves.move_line_ids), "; ".join(notes) or "khớp")


groups = {}
for picking in Picking.search([("state", "in", OPEN), ("location_id", "in", transit_area.ids)]):
    if not picking.source_transfer_id:
        report["skip"].append((picking.name, "bước 2: không có phiếu bước 1 (source_transfer_id) để biết kho nguồn"))
        continue
    groups[picking.source_transfer_id] = groups.get(picking.source_transfer_id, Picking) | picking
for src, open_pickings in groups.items():
    run(src.name, lambda s=src, o=open_pickings: migrate_group(s, o), "step2")

# ---------- Báo cáo ----------
print("\nA. Bước 1 đổi đích (%s):" % len(report["step1"]))
for row in report["step1"]:
    print("  %s %s" % row)
print("\nB. Bước 2 theo phiếu bước 1 (%s):" % len(report["step2"]))
for row in report["step2"]:
    print("  %s: %s" % row)
print("\nBỏ qua (%s):" % len(report["skip"]))
for row in report["skip"]:
    print("  %s: %s" % row)
print("\nC. Bước 1 đã xong, chưa có phiếu bước 2 (hàng nằm ở Transit):")
for p in Picking.search([("state", "=", "done"), ("location_dest_id", "in", transit_area.ids),
                         ("second_transfer_created", "=", False)]):
    print("  %s | %s" % (p.name, p.date_done))
print("\nD. Tồn còn ở Transit:")
for q in Quant.search([("location_id", "in", transit_area.ids), ("quantity", "!=", 0)]):
    print("  %s | %s | lô %s | kiện %s | tồn %s | giữ %s" % (
        q.location_id.complete_name, q.product_id.display_name, q.lot_id.name or "-",
        q.package_id.name or "-", q.quantity, q.reserved_quantity))

if DRY_RUN:
    env.cr.rollback()
    print("\nDRY_RUN: đã rollback, chưa ghi gì.")
else:
    env.cr.commit()
    print("\nĐã commit.")
