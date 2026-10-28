# Tình trạng các vị trí XUẤT SỬ DỤNG (SUDUNG-*) của từng kho: có chưa, nằm đâu, có bị tính vào tồn không, đang chứa
# bao nhiêu hàng, đã có bao nhiêu dịch chuyển, loại hoạt động / phiếu nào đang trỏ vào.
#
# Vị trí đúng: ngoài mọi kho, usage KHÔNG phải internal (thường là inventory, nằm dưới Virtual Locations). Vị trí nội
# bộ hoặc nằm trong kho thì hàng xuất sang vẫn bị cộng vào tồn — báo [SAI].
# SL trong vị trí là tổng đã xuất sử dụng tới giờ (Odoo vẫn ghi quant ở vị trí ảo), không phải hàng còn trong kho.
#
# CHỈ ĐỌC — không ghi gì. Thiếu vị trí thì bin/create_picking_type_xuat_su_dung.py tự tạo khi tạo loại hoạt động.
# CÁCH CHẠY: copy TOÀN BỘ file dán vào `odoo-bin shell` (Odoo.sh → Shell, hoặc notebook Odoo-shell).
exec(r'''
# ── CẤU HÌNH ─────────────────────────────────────────────────────────────────
MAPPING = {                    # mã kho → tên / tên đầy đủ / mã vạch của vị trí sử dụng
    "KDN": "SUDUNG-DN",
    "KBC": "SUDUNG-KBC",
    "KHD": "SUDUNG-KHD",
    "TSN": "SUDUNG-TSN",
}
SEARCH_TEXT = "sudung"         # quét thêm vị trí lạ có chữ này mà không nằm trong MAPPING
# ─────────────────────────────────────────────────────────────────────────────


def find_location(key):
    """Các vị trí khớp đúng key theo name / complete_name / barcode, không phân biệt hoa thường."""
    return env["stock.location"].with_context(active_test=False).search([
        "|", "|", ("name", "=ilike", key), ("complete_name", "=ilike", key), ("barcode", "=ilike", key)])


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
    open_pickings = env["stock.picking"].search([
        "|", ("location_dest_id", "=", loc.id), ("location_id", "=", loc.id),
        ("state", "not in", ("done", "cancel"))])
    if open_pickings:
        print("    Phiếu đang mở: %s" % ", ".join(open_pickings.mapped(lambda p: "%s (%s)" % (p.name, p.state))))
    types = env["stock.picking.type"].with_context(active_test=False).search([
        "|", ("default_location_src_id", "=", loc.id), ("default_location_dest_id", "=", loc.id)])
    for pt in types:
        print("    ← loại hoạt động #%s %s (%s)%s" % (pt.id, pt.display_name, pt.code, "" if pt.active else " [LƯU TRỮ]"))
    if not types:
        print("    ← chưa loại hoạt động nào trỏ vào")


def run():
    print("DB: %s" % env.cr.dbname)
    seen = env["stock.location"]
    for wh_code, key in MAPPING.items():
        wh = env["stock.warehouse"].search([("code", "=", wh_code)])
        print("\n=== %s → %s" % (wh_code, key))
        if len(wh) != 1:
            print("    [SAI] mã kho %s ra %s kho" % (wh_code, len(wh)))
            continue
        found = find_location(key)
        seen |= found
        if not found:
            print("    [CHƯA CÓ] chưa có vị trí '%s'" % key)
            continue
        if len(found) > 1:
            print("    [SAI] khớp %s vị trí: %s" % (len(found), ", ".join(found.mapped("complete_name"))))
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


run()
''')
