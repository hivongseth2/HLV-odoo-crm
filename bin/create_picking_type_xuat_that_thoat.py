# Tạo loại hoạt động "Xuất kho thất thoát" cho từng kho: nguồn = vị trí tồn của kho, đích = vị trí <kho>_LOSS.
#
# Vị trí LOSS phải có sẵn — chạy bin/check_loss_locations.py trước (script đó kiểm và tạo vị trí, mã vạch theo kiểu
# KBCLOSS). Script này KHÔNG tự tạo vị trí. Vị trí tìm theo tên, tên đầy đủ hoặc mã vạch. Vị trí LOSS KHÔNG được nằm
# trong kho hay là vị trí nội bộ: hàng xuất sang đó vẫn bị tính là tồn của kho, nhìn báo cáo tưởng còn hàng thật.
# Vị trí vi phạm → bỏ qua kho đó và báo, không dùng.
#
# Kho đã có loại cùng tên, hoặc đã có loại cùng mã loại trỏ đích vào vị trí đó (kể cả đã lưu trữ) → bỏ qua, không
# tạo trùng. Các tuỳ chọn giữ chỗ/backorder/lô chép theo loại "Lệnh giao hàng" của kho cho cùng cách xử lý.
#
# Mã loại "internal" chứ không "outgoing": amis_callback đẩy MỌI phiếu outgoing đã xác nhận sang MISA (kể cả phiếu
# không có đơn bán), và nhiều module khác (ZNS, đối soát MISA, điều phối giao) lọc theo outgoing.
#
# CÁCH CHẠY: sửa CẤU HÌNH, copy TOÀN BỘ file dán vào `odoo-bin shell`. Mặc định CHẠY THỬ: chỉ in việc sẽ làm.
# Xem đúng rồi đổi DRY_RUN = False và chạy lại — script tự commit.
exec(r'''
# ── CẤU HÌNH ─────────────────────────────────────────────────────────────────
TYPE_NAME = "Xuất kho thất thoát"
OP_CODE = "internal"           # internal = Dịch chuyển nội bộ; outgoing = Giao hàng (bị đẩy sang MISA)
SEQUENCE_CODE = "TT"           # số phiếu thành <mã kho>/TT/00001
BARCODE_SUFFIX = "TT"          # mã vạch loại hoạt động = <mã kho> + TT (như TSNIN của Phiếu nhập kho)
MAPPING = {                    # mã kho → tên / tên đầy đủ / mã vạch của vị trí thất thoát
    "KDN": "KDN_LOSS",
    "KBC": "KBC_LOSS",
    "KHD": "KHD_LOSS",
    "TSN": "TSN_LOSS",
    "TSNSR": "TSNSR_LOSS",
}
DRY_RUN = False
# ─────────────────────────────────────────────────────────────────────────────

COPIED_FROM_DELIVERY = ("reservation_method", "reservation_days_before", "reservation_days_before_priority",
                        "create_backorder", "move_type", "use_existing_lots", "show_entire_packs")


def find_location(key):
    """Các vị trí khớp đúng key theo name / complete_name / barcode, không phân biệt hoa thường."""
    return env["stock.location"].with_context(active_test=False).search([
        "|", "|", ("name", "=ilike", key), ("complete_name", "=ilike", key), ("barcode", "=ilike", key)])


def location_problem(loc, wh):
    """Lý do vị trí sẵn có không dùng được làm đích xuất thất thoát, hoặc None."""
    if loc.usage == "internal" or loc.warehouse_id:
        return "vị trí nội bộ / nằm trong kho %s — hàng xuất sang vẫn cộng tồn" % (loc.warehouse_id.name or "")
    if loc.company_id and loc.company_id != wh.company_id:
        return "vị trí thuộc công ty %s, kho thuộc %s" % (loc.company_id.name, wh.company_id.name)
    if not loc.active:
        return "vị trí đang lưu trữ — mở lại trên giao diện rồi chạy lại"
    return None


def existing_type(PickingType, wh, loc):
    return PickingType.search([
        ("warehouse_id", "=", wh.id),
        "|", ("name", "=", TYPE_NAME),
        "&", ("code", "=", OP_CODE), ("default_location_dest_id", "=", loc.id),
    ], limit=1)


def type_barcode(PickingType, wh):
    barcode = (wh.code or "").replace(" ", "").upper() + BARCODE_SUFFIX
    if PickingType.search_count([("barcode", "=", barcode)]):
        print("    [!] mã vạch %s đã có loại khác dùng — để trống mã vạch" % barcode)
        return False
    return barcode


def build_vals(wh, loc, barcode):
    delivery = wh.out_type_id
    vals = {
        "name": TYPE_NAME,
        "code": OP_CODE,
        "sequence_code": SEQUENCE_CODE,
        "warehouse_id": wh.id,
        "company_id": wh.company_id.id,
        "default_location_src_id": wh.lot_stock_id.id,
        "default_location_dest_id": loc.id,
        "barcode": barcode,
        "sequence": (delivery.sequence or 0) + 1,
    }
    if delivery:
        vals.update({field: delivery[field] for field in COPIED_FROM_DELIVERY})
    return vals


def plan_one(PickingType, wh_code, loc_key):
    """(kho, vị trí, mã vạch loại) — hoặc None nếu bỏ qua (đã in lý do)."""
    print("\n%s → %s" % (wh_code, loc_key))
    wh = env["stock.warehouse"].search([("code", "=", wh_code)])
    if len(wh) != 1:
        print("    [BỎ QUA] mã kho %s ra %s kho" % (wh_code, len(wh)))
        return None
    loc = find_location(loc_key)
    if not loc:
        print("    [BỎ QUA] chưa có vị trí '%s' — chạy bin/check_loss_locations.py để tạo trước" % loc_key)
        return None
    if len(loc) > 1:
        print("    [BỎ QUA] '%s' khớp %s vị trí: %s" % (loc_key, len(loc), ", ".join(loc.mapped("complete_name"))))
        return None
    problem = location_problem(loc, wh)
    if problem:
        print("    [BỎ QUA] %s: %s" % (loc.complete_name, problem))
        return None
    print("    vị trí: %s (usage=%s)" % (loc.complete_name, loc.usage))
    current = existing_type(PickingType, wh, loc)
    if current:
        print("    [ĐÃ CÓ LOẠI] #%s %s (%s → %s)%s" % (
            current.id, current.display_name, current.default_location_src_id.complete_name,
            current.default_location_dest_id.complete_name, "" if current.active else " [LƯU TRỮ]"))
        return None
    barcode = type_barcode(PickingType, wh)
    print("    [SẼ TẠO LOẠI] %s: %s → %s · mã loại %s · số phiếu %s/%s/xxxxx · mã vạch %s" % (
        wh.name, wh.lot_stock_id.complete_name, loc.complete_name, OP_CODE,
        wh.code, SEQUENCE_CODE, barcode or "—"))
    return wh, loc, barcode


def run():
    # Tạo bằng lang vi_VN: name là field dịch, ghi một lần ra cả vi_VN lẫn en_US.
    PickingType = env["stock.picking.type"].with_context(lang="vi_VN", active_test=False)
    print("DB: %s" % env.cr.dbname)
    plans = [plan for plan in (plan_one(PickingType, code, key) for code, key in MAPPING.items()) if plan]
    if not plans:
        print("\nKhông có gì để tạo.")
        return
    if DRY_RUN:
        print("\nCHẠY THỬ — sẽ tạo %s loại hoạt động, chưa ghi gì. Đúng thì đổi DRY_RUN = False rồi chạy lại."
              % len(plans))
        return
    created = PickingType.create([build_vals(wh, loc, barcode) for wh, loc, barcode in plans])
    env.cr.commit()
    print("\nĐã tạo và commit %s loại hoạt động:" % len(created))
    for pt in created:
        print("    #%s %s · %s → %s · trình tự %s" % (
            pt.id, pt.display_name, pt.default_location_src_id.complete_name,
            pt.default_location_dest_id.complete_name, pt.sequence_id.prefix))


run()
''')
