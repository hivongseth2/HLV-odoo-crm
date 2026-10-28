# Liệt kê LOẠI HOẠT ĐỘNG (stock.picking.type) theo từng kho + các vị trí SUDUNG-* — xem trước khi tạo loại
# "Xuất kho sử dụng" bằng bin/create_picking_type_xuat_su_dung.py.
#
# In ra: mỗi kho (mã, công ty, vị trí tồn), từng loại hoạt động của kho đó (kể cả đã lưu trữ) với mã loại, tiền tố
# trình tự, mã vạch, vị trí nguồn/đích mặc định, loại trả hàng, số phiếu; rồi các vị trí có "sudung" trong tên
# đầy đủ hoặc mã vạch (usage, kho, công ty) và loại hoạt động nào đang trỏ vào chúng.
#
# CHỈ ĐỌC — không ghi gì.
# CÁCH CHẠY: copy TOÀN BỘ file dán vào `odoo-bin shell` (Odoo.sh → Shell, hoặc notebook Odoo-shell).
exec(r'''
SEARCH_TEXT = "_loss"


def loc_label(loc):
    return loc.complete_name if loc else "—"


def print_type(pt, picking_counts):
    print("    #%-4s %-32s %-9s seq=%-6s prefix=%-14s barcode=%-10s%s" % (
        pt.id, (pt.name or "")[:32], pt.code, pt.sequence_code or "", pt.sequence_id.prefix or "",
        pt.barcode or "", "" if pt.active else "  [LƯU TRỮ]"))
    print("          %s → %s · trả hàng: %s · %s phiếu" % (
        loc_label(pt.default_location_src_id), loc_label(pt.default_location_dest_id),
        pt.return_picking_type_id.display_name or "—", picking_counts.get(pt.id, 0)))


def run():
    PickingType = env["stock.picking.type"].with_context(lang="vi_VN", active_test=False)
    Location = env["stock.location"].with_context(active_test=False)
    picking_counts = {
        row["picking_type_id"][0]: row["picking_type_id_count"]
        for row in env["stock.picking"].read_group([], ["picking_type_id"], ["picking_type_id"])
        if row["picking_type_id"]
    }

    for wh in env["stock.warehouse"].with_context(active_test=False).search([], order="company_id, id"):
        print("\n=== KHO #%s %s · mã %s · %s · tồn: %s%s" % (
            wh.id, wh.name, wh.code, wh.company_id.name, loc_label(wh.lot_stock_id),
            "" if wh.active else " [LƯU TRỮ]"))
        print("    out_type_id = %s" % (wh.out_type_id.display_name or "—"))
        for pt in PickingType.search([("warehouse_id", "=", wh.id)], order="sequence, id"):
            print_type(pt, picking_counts)

    orphan = PickingType.search([("warehouse_id", "=", False)], order="id")
    if orphan:
        print("\n=== LOẠI HOẠT ĐỘNG KHÔNG GẮN KHO")
        for pt in orphan:
            print_type(pt, picking_counts)

    # Ô chọn vị trí tìm theo cả complete_name lẫn barcode — "SUDUNG-DN" thấy ở dropdown có thể là mã vạch,
    # nên quét cả hai và in repr(name) để lộ gạch dài / dấu cách lạ.
    print("\n=== VỊ TRÍ có '%s' trong tên đầy đủ hoặc mã vạch" % SEARCH_TEXT)
    locations = Location.search(["|", ("complete_name", "ilike", SEARCH_TEXT),
                                 ("barcode", "ilike", SEARCH_TEXT)], order="complete_name")
    if not locations:
        print("    (không có — kiểm lại đang chạy đúng DB chưa: %s)" % env.cr.dbname)
    for loc in locations:
        print("    #%-5s %-30s name=%r barcode=%r" % (loc.id, loc.complete_name, loc.name, loc.barcode))
        print("           usage=%-9s kho=%-20s công ty=%s%s" % (
            loc.usage, loc.warehouse_id.name or "—",
            loc.company_id.name or "—", "" if loc.active else " [LƯU TRỮ]"))
        users = PickingType.search(["|", ("default_location_src_id", "=", loc.id),
                                    ("default_location_dest_id", "=", loc.id)])
        for pt in users:
            print("           ← đang dùng bởi #%s %s (%s)" % (pt.id, pt.display_name, pt.code))

    print("\n=== LOẠI HOẠT ĐỘNG TÊN CÓ 'sử dụng' hoặc '%s'" % SEARCH_TEXT)
    for pt in PickingType.search(["|", ("name", "ilike", "sử dụng"), ("name", "ilike", SEARCH_TEXT)]):
        print_type(pt, picking_counts)


run()
''')
