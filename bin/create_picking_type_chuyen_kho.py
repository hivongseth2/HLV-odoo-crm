# Tách chuyển kho 2 bước khỏi "Lệnh chuyển hàng nội bộ" (INT): tạo cho MỖI KHO đang hoạt động 2 loại hoạt động
#   - "Chuyển kho đi"   (CKD, bước 1): Tồn kho của kho → CHUYENKHO của kho, đánh dấu chuyển kho 2 bước = Xuất kho
#   - "Nhận chuyển kho" (CKN, bước 2): CHUYENKHO → Tồn kho gốc của kho,   đánh dấu chuyển kho 2 bước = Nhập kho
# Code (deltatech_picking_transit: warehouse._hlv_transfer_out_type / _hlv_transfer_in_type) tự dùng 2 loại này khi
# có; kho chưa có thì vẫn chạy bằng INT như cũ. Nguồn mặc định của CKN là CHUYENKHO của chính kho — phiếu bước 2 thật
# luôn lấy nguồn = đích phiếu bước 1 (CHUYENKHO kho gửi), Odoo chỉ bắt buộc loại phải có nguồn mặc định.
#
# Bỏ qua kho: chưa có CHUYENKHO (nâng cấp deltatech_picking_transit để tạo), hoặc đã có loại cùng mã trình tự (kể cả
# lưu trữ), hoặc đã có loại KHÁC đánh dấu cùng chiều (báo ra để gỡ dấu trước — 2 loại cùng chiều thì code lấy loại
# đầu tiên, không chắc là loại nào). Các tuỳ chọn giữ chỗ/backorder/lô chép theo INT của kho cho cùng cách xử lý.
# Công ty có giới hạn loại phiếu quét trên app (hlv_barcode_picking_type_ids) mà INT nằm trong đó thì thêm 2 loại mới
# vào, không thì app báo "loại phiếu không được phép".
#
# Chạy SAU khi đã deploy + nâng cấp hlv_warehouse_permission, hlv_mobile_barcode (có mã quyền CKD/CKN).
# CÁCH CHẠY: copy TOÀN BỘ file dán vào `odoo-bin shell`. Mặc định CHẠY THỬ: chỉ in việc sẽ làm.
# Xem đúng rồi đổi DRY_RUN = False và chạy lại — script tự commit.
exec(r'''
# ── CẤU HÌNH ─────────────────────────────────────────────────────────────────
TYPES = (                      # (chiều chuyển kho 2 bước, tên, mã trình tự)
    ("delivery", "Chuyển kho đi", "CKD"),
    ("reception", "Nhận chuyển kho", "CKN"),
)
EXCLUDE_WAREHOUSE_CODES = ()   # vd ("WLTSN",) — kho không tạo
DRY_RUN = False
# ─────────────────────────────────────────────────────────────────────────────

COPIED_FROM_INT = ("reservation_method", "reservation_days_before", "reservation_days_before_priority",
                   "create_backorder", "move_type", "use_existing_lots", "show_entire_packs")


def transfer_location(wh):
    """CHUYENKHO của kho — chỉ tìm, không tạo (chạy thử không được ghi)."""
    return env["stock.location"].search([("hlv_is_transfer_location", "=", True), ("warehouse_id", "=", wh.id)], limit=1)


def type_barcode(PickingType, wh, seq_code):
    barcode = (wh.code or "").replace(" ", "").upper() + seq_code
    if PickingType.search_count([("barcode", "=", barcode)]):
        print("    [!] mã vạch %s đã có loại khác dùng — để trống mã vạch" % barcode)
        return False
    return barcode


def build_vals(PickingType, wh, hub, use, name, seq_code):
    src, dest = (wh.lot_stock_id, hub) if use == "delivery" else (hub, wh.lot_stock_id)
    vals = {
        "name": name,
        "code": "internal",
        "sequence_code": seq_code,
        "warehouse_id": wh.id,
        "company_id": wh.company_id.id,
        "default_location_src_id": src.id,
        "default_location_dest_id": dest.id,
        "barcode": type_barcode(PickingType, wh, seq_code),
        "two_step_transfer_use": use,
        "sequence": (wh.int_type_id.sequence or 0) + 1,
    }
    if wh.int_type_id:
        vals.update({field: wh.int_type_id[field] for field in COPIED_FROM_INT})
    return vals


def plan_warehouse(PickingType, wh):
    """vals các loại cần tạo cho kho wh (đã in lý do bỏ qua)."""
    print("\n=== %s (%s) · tồn: %s" % (wh.name, wh.code, wh.lot_stock_id.complete_name))
    hub = transfer_location(wh)
    if not hub:
        print("    [BỎ QUA] kho chưa có CHUYENKHO — nâng cấp deltatech_picking_transit để tạo")
        return []
    vals_list = []
    for use, name, seq_code in TYPES:
        same_code = PickingType.search([("warehouse_id", "=", wh.id), ("sequence_code", "=", seq_code)], limit=1)
        if same_code:
            print("    [ĐÃ CÓ] %s: #%s %s%s" % (seq_code, same_code.id, same_code.name, "" if same_code.active else " [LƯU TRỮ]"))
            continue
        flagged = PickingType.search([("warehouse_id", "=", wh.id), ("two_step_transfer_use", "=", use)])
        if flagged:
            print("    [BỎ QUA] %s: đã có loại đánh dấu '%s': %s — gỡ dấu trên loại đó rồi chạy lại" % (
                seq_code, use, ", ".join(flagged.mapped(lambda t: "#%s %s" % (t.id, t.name)))))
            continue
        vals = build_vals(PickingType, wh, hub, use, name, seq_code)
        src = env["stock.location"].browse(vals["default_location_src_id"])
        dest = env["stock.location"].browse(vals["default_location_dest_id"])
        print("    [SẼ TẠO] %s %s: %s → %s · số phiếu %s/%s/xxxxx · mã vạch %s" % (
            seq_code, name, src.complete_name, dest.complete_name, wh.code, seq_code, vals["barcode"] or "—"))
        vals_list.append(vals)
    return vals_list


def allow_on_mobile(created):
    """Thêm loại mới vào danh sách loại phiếu được quét trên app của công ty — chỉ khi công ty có giới hạn và INT
    của kho nằm trong đó (danh sách rỗng = cho mọi loại, không cần thêm)."""
    if "hlv_barcode_picking_type_ids" not in env["res.company"]._fields:
        return
    for company in created.company_id:
        allowed = company.hlv_barcode_picking_type_ids
        if not allowed:
            continue
        to_add = created.filtered(lambda t: t.company_id == company and t.warehouse_id.int_type_id in allowed)
        if to_add:
            company.hlv_barcode_picking_type_ids = [(4, t.id) for t in to_add]
            print("    + cho quét trên app (%s): %s" % (company.name, ", ".join(to_add.mapped("display_name"))))


def run():
    # Tạo bằng lang vi_VN: name là field dịch, ghi một lần ra cả vi_VN lẫn en_US.
    PickingType = env["stock.picking.type"].with_context(lang="vi_VN", active_test=False)
    print("DB: %s" % env.cr.dbname)
    if "two_step_transfer_use" not in PickingType._fields:
        print("Chưa cài deltatech_picking_transit — dừng.")
        return
    warehouses = env["stock.warehouse"].search([("code", "not in", list(EXCLUDE_WAREHOUSE_CODES))], order="id")
    vals_list = [vals for wh in warehouses for vals in plan_warehouse(PickingType, wh)]
    if not vals_list:
        print("\nKhông có gì để tạo.")
        return
    if DRY_RUN:
        print("\nCHẠY THỬ — sẽ tạo %s loại hoạt động, chưa ghi gì. Đúng thì đổi DRY_RUN = False rồi chạy lại."
              % len(vals_list))
        return
    created = PickingType.create(vals_list)
    allow_on_mobile(created)
    env.cr.commit()
    print("\nĐã tạo và commit %s loại hoạt động:" % len(created))
    for pt in created:
        print("    #%s %s · %s → %s · trình tự %s" % (
            pt.id, pt.display_name, pt.default_location_src_id.complete_name,
            pt.default_location_dest_id.complete_name, pt.sequence_id.prefix))


run()
''')
