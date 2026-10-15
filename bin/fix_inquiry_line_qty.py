# Sửa SL hỏi / mô tả của MỘT dòng phiếu hỏi giá (hlv_vendor_quotation) — vd HG/26/00158: sale bấm "+ Thêm sản phẩm"
# hai lần với BLMCD-20, dòng cũ bị cộng dồn 8 → 24 trong khi chỉ cần 8.
#
# CÁCH CHẠY: sửa CẤU HÌNH bên dưới, copy TOÀN BỘ file dán vào `odoo-bin shell` (Odoo.sh → Shell). Mặc định CHẠY THỬ:
# chỉ in hiện trạng + việc sẽ làm, không ghi gì. Xem đúng rồi đổi DRY_RUN = False và chạy lại — script tự commit.
# Cả script nằm trong exec(r'''...''') để dán vào shell tương tác không vỡ (dòng trống trong hàm không cắt khối lệnh).
exec(r'''
# ── CẤU HÌNH ─────────────────────────────────────────────────────────────────
INQUIRY = "HG/26/00158"     # số phiếu hỏi giá
PRODUCT_CODE = "BLMCD-20"   # mã sản phẩm (default_code) của dòng cần sửa
NEW_QTY = 8                 # SL hỏi đúng — SL cần mua về cùng số này
RENAME = True               # True = mô tả dòng (phiếu + báo giá NCC đang mở) đổi theo tên sản phẩm hiện tại
DRY_RUN = True              # True = chỉ in, không ghi
# ─────────────────────────────────────────────────────────────────────────────

OPEN_QUOTE_STATES = ("sent", "quoted")


def run():
    inquiry = env["hlv.vendor.inquiry"].sudo().search([("name", "=", INQUIRY)], limit=1)
    if not inquiry:
        print("Không thấy phiếu %s." % INQUIRY)
        return
    lines = inquiry.line_ids.filtered(lambda l: l.product_id.default_code == PRODUCT_CODE)
    if len(lines) != 1:
        print("Phiếu %s có %s dòng mã %s — cần đúng 1 dòng, dừng." % (INQUIRY, len(lines), PRODUCT_CODE))
        return
    line = lines
    product_name = line.product_id.display_name
    print("Phiếu %s (%s) — dòng #%s" % (inquiry.name, inquiry.state, line.id))
    print("  Mô tả      : %s" % line.name)
    print("  Sản phẩm   : %s" % product_name)
    print("  SL hỏi     : %s → %s" % (line.product_qty, NEW_QTY))
    print("  SL cần mua : %s → %s" % (line.need_qty, NEW_QTY))
    for quote_line in line.quote_line_ids:
        print("  Báo giá %-16s %-40s SL %-6s %s%s%s" % (
            quote_line.quote_id.name, quote_line.quote_id.partner_id.commercial_partner_id.display_name[:40],
            quote_line.product_qty, quote_line.quote_id.state,
            " · đã thu hồi" if quote_line.withdrawn else "", " · đã lên đơn mua" if quote_line.vendor_locked else ""))
    if line.request_line_ids:
        # Đã lên YCMH: SL mua nằm trên YCMH / đơn mua — sửa tay ở đó, script không đụng.
        print("[DỪNG] Dòng đã lên YCMH (%s) — sửa trên YCMH / đơn mua, không sửa bằng script này."
              % ", ".join(line.request_line_ids.request_id.mapped("name")))
        return
    if NEW_QTY <= 0:
        print("[DỪNG] NEW_QTY phải lớn hơn 0.")
        return
    quote_lines = line.quote_line_ids.filtered(
        lambda q: q.quote_id.state in OPEN_QUOTE_STATES and not q.vendor_locked)
    if DRY_RUN:
        print("\nCHẠY THỬ — chưa ghi gì. Đúng thì đổi DRY_RUN = False rồi chạy lại.")
        return
    before = line.product_qty
    old_name = line.name
    line.write({"product_qty": NEW_QTY, "need_qty": NEW_QTY})
    quote_lines.write({"product_qty": NEW_QTY})
    if RENAME and old_name != product_name:
        line.name = product_name
        quote_lines.write({"name": product_name})
    inquiry.message_post(body="Sửa dữ liệu (script): %s — SL hỏi %s → %s%s." % (
        PRODUCT_CODE, before, NEW_QTY, "; mô tả \"%s\" → \"%s\"" % (old_name, product_name)
        if RENAME and old_name != product_name else ""))
    env.cr.commit()
    print("\nĐã sửa và commit.")


run()
''', {"env": env})  # noqa: F821 — env có sẵn trong odoo-bin shell
