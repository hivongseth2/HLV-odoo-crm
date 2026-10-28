# Tình trạng các vị trí XUẤT THẤT THOÁT (<kho>_LOSS) của từng kho, kho nào chưa có thì tạo.
#
# Vị trí đúng: ngoài mọi kho, usage KHÔNG phải internal. Tạo mới thì dưới Virtual Locations, usage = inventory, mã
# vạch theo kiểu KBC_LOSS đang có (KBCLOSS). Vị trí sẵn có mà nội bộ / nằm trong kho thì hàng xuất sang vẫn bị cộng
# vào tồn — báo [SAI], KHÔNG tự sửa (đổi usage vị trí đang có hàng phải xem tay).
# SL trong vị trí là tổng đã xuất thất thoát tới giờ (Odoo vẫn ghi quant ở vị trí ảo), không phải hàng còn trong kho.
#
# Chạy trước bin/create_picking_type_xuat_that_thoat.py — script đó không tự tạo vị trí.
# CÁCH CHẠY: sửa CẤU HÌNH, copy TOÀN BỘ file dán vào `odoo-bin shell`. Mặc định CHẠY THỬ: chỉ in tình trạng + việc
# sẽ làm. Đúng rồi đổi DRY_RUN = False và chạy lại — script tự commit.
exec(r'''
# ── CẤU HÌNH ─────────────────────────────────────────────────────────────────
MAPPING = {                    # mã kho → (tên vị trí, mã vạch)
    "TSN": ("TSN_LOSS", "TSNLOSS"),
    "KBC": ("KBC_LOSS", "KBCLOSS"),
}
NEW_LOCATION_USAGE = "inventory"
SEARCH_TEXT = "loss"           # quét thêm vị trí lạ có chữ này mà không nằm trong MAPPING
DRY_RUN = True
# ─────────────────────────────────────────────────────────────────────────────


def find_location(name, barcode):
    """Các vị trí khớp tên / tên đầy đủ / mã vạch (không phân biệt hoa thường) — tìm cả mã vạch để không tạo trùng."""
    return env["stock.location"].with_context(active_test=False).search([
        "|", "|", "|", ("name", "=ilike", name), ("complete_name", "=ilike", name),
        ("barcode", "=ilike", name), ("barcode", "=ilike", barcode)])


def location_problems(loc, wh):
    """Danh sách lý do vị trí không dùng được làm đích xuất ra khỏi tồn của kho wh (rỗng = ổn)."""
    problems = []
    if loc.usage == "internal" or loc.warehouse_id:
        problems.append("vị trí nội bộ / nằm trong kho %s — hàng xuất sang vẫn cộng tồn" % (loc.warehouse_id.name or ""))
    if loc.company_id and loc.company_id != wh.company_id:
        problems.append("thuộc công ty %s, kho thuộc %s" % (loc.company_id.name, wh.company_id.name))
    if not loc.active:
        problems.append("đang lưu trữ")
    return problems


def print_location_status(loc):
    quants = env["stock.quant"].search([("location_id", "=", loc.id)]).filtered("quantity")
    print("    SL đang ghi ở vị trí: %s mã · tổng %s%s" % (
        len(quants.product_id), sum(quants.mapped("quantity")),
        " · %s quant ÂM" % len(quants.filtered(lambda q: q.quantity < 0)) if quants.filtered(lambda q: q.quantity < 0) else ""))
    MoveLine = env["stock.move.line"]
    done_in = MoveLine.search_count([("location_dest_id", "=", loc.id), ("state", "=", "done")])
    done_out = MoveLine.search_count([("location_id", "=", loc.id), ("state", "=", "done")])
    last = MoveLine.search(["|", ("location_dest_id", "=", loc.id), ("location_id", "=", loc.id),
                            ("state", "=", "done")], order="date desc", limit=1)
    print("    Dịch chuyển xong: %s dòng vào · %s dòng ra · gần nhất %s" % (
        done_in, done_out, last.date or "—"))
    types = env["stock.picking.type"].with_context(active_test=False).search([
        "|", ("default_location_src_id", "=", loc.id), ("default_location_dest_id", "=", loc.id)])
    for pt in types:
        print("    ← loại hoạt động #%s %s (%s)%s" % (pt.id, pt.display_name, pt.code, "" if pt.active else " [LƯU TRỮ]"))
    if not types:
        print("    ← chưa loại hoạt động nào trỏ vào")


def run():
    print("DB: %s" % env.cr.dbname)
    seen = env["stock.location"]
    to_create = []
    for wh_code, (name, barcode) in MAPPING.items():
        wh = env["stock.warehouse"].search([("code", "=", wh_code)])
        print("\n=== %s → %s" % (wh_code, name))
        if len(wh) != 1:
            print("    [SAI] mã kho %s ra %s kho" % (wh_code, len(wh)))
            continue
        found = find_location(name, barcode)
        seen |= found
        if len(found) > 1:
            print("    [SAI] khớp %s vị trí: %s" % (len(found), ", ".join(found.mapped("complete_name"))))
            continue
        if not found:
            print("    [SẼ TẠO] Virtual Locations/%s · usage=%s · mã vạch %s · %s" % (
                name, NEW_LOCATION_USAGE, barcode, wh.company_id.name))
            to_create.append({
                "name": name,
                "barcode": barcode,
                "usage": NEW_LOCATION_USAGE,
                "location_id": env.ref("stock.stock_location_locations_virtual").id,
                "company_id": wh.company_id.id,
            })
            continue
        problems = location_problems(found, wh)
        print("    %s #%s %s · usage=%s · mã vạch %s · %s" % (
            "[SAI]" if problems else "[OK]", found.id, found.complete_name, found.usage,
            found.barcode or "—", found.company_id.name or "mọi công ty"))
        for problem in problems:
            print("      - %s" % problem)
        print_location_status(found)

    others = env["stock.location"].with_context(active_test=False).search([
        "|", ("complete_name", "ilike", SEARCH_TEXT), ("barcode", "ilike", SEARCH_TEXT)]) - seen
    if others:
        print("\n=== Vị trí khác có '%s' (không nằm trong MAPPING)" % SEARCH_TEXT)
        for loc in others:
            print("    #%s %s · usage=%s · kho %s%s" % (
                loc.id, loc.complete_name, loc.usage, loc.warehouse_id.name or "—", "" if loc.active else " [LƯU TRỮ]"))

    if not to_create:
        print("\nKhông có vị trí nào cần tạo.")
        return
    if DRY_RUN:
        print("\nCHẠY THỬ — sẽ tạo %s vị trí, chưa ghi gì. Đúng thì đổi DRY_RUN = False rồi chạy lại." % len(to_create))
        return
    created = env["stock.location"].create(to_create)
    env.cr.commit()
    print("\nĐã tạo và commit %s vị trí:" % len(created))
    for loc in created:
        print("    #%s %s · mã vạch %s" % (loc.id, loc.complete_name, loc.barcode))


run()
''')
