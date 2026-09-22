# -*- coding: utf-8 -*-
"""
reset_wrong_printed_pick_slips.py
==================================
Đưa các phiếu lấy hàng bị auto-print gửi in SAI (in khi còn thiếu hàng, xem
bin/check_auto_print_partial_stock.py) về trạng thái CHƯA IN, để chúng rời khỏi cột
"ĐÃ IN, CHỜ ĐÓNG GÓI" trên /sale_plan và được xử lý lại từ đầu.

Cột "ĐÃ IN, CHỜ ĐÓNG GÓI" gom ĐƠN có ``has_active_pick_printed`` (xem
services/delivery_planner_stock.py), tức là:
  (a) phiếu PICK CÒN ĐANG MỞ mà x_printed = True — nhưng KHÔNG phải cái nào cũng in sai:
      đo trên PRD 22/09 có 22 phiếu như vậy, trong đó chỉ 12 phiếu do hệ thống tự in khi
      còn thiếu hàng; 9 phiếu là NGƯỜI chủ động bấm in (4 trong số đó in phiếu thiếu hàng
      một cách có ý thức — sale xem "có gì giao nấy" rồi in), 1 phiếu hệ thống in nhưng
      hàng đã đủ nên in đúng. Vì vậy phạm vi sửa do CHE_DO quyết định, mặc định chỉ lấy
      nhóm "hệ thống in + còn thiếu hàng".
  (b) phiếu PICK đã DONE + có PACK đang mở -> hàng đã lấy xong thật, chỉ chờ đóng gói.
      KHÔNG sửa nhóm này: đưa nó về "chưa in" là xoá dấu vết một lần lấy hàng đã xảy ra
      thật, và đơn sẽ nhảy sang cột "Có hàng chưa đóng gói" gây hiểu sai cho kho.
Script in ra tất cả, chỉ GHI lên những dòng đánh CÓ ở cột "sẽ sửa".

⚠️ SCRIPT NÀY GHI DỮ LIỆU:
  - stock.picking.x_printed          -> False
  - stock.picking.x_auto_print_requested -> False  (để khi hàng về đủ, cron đã sửa còn gửi
    in lại được; giữ True là phiếu bị loại vĩnh viễn khỏi auto-print)
  - ghi 1 dòng chatter lên từng phiếu nói rõ vì sao bị đưa về chưa in
KHÔNG đụng: mốc thời gian in (x_pick_print_start_at/end_at, x_pick_printed_by_id) — giữ lại
làm dấu vết đối soát; hàng chờ in (hlv.iot.print.queue) — giữ nguyên lịch sử đã gửi gì.

CẤU HÌNH HIỆN TẠI: kho Bến Cam (MA_KHO='KBC'), reset MỌI phiếu còn mở đang mang cờ đã in
(CHE_DO='tat_ca_con_mo'), và GHI THẬT (CHI_XEM=False) — theo yêu cầu "18 phiếu của kho Bến
Cam thôi, reset tất cả". Đặt CHI_XEM = True nếu muốn xem lại danh sách mà chưa ghi.

Vì sao không chốt bằng đúng con số 18: cột trên màn hình đếm theo ĐƠN và chỉ đếm đơn CHƯA
sang trạng thái khác, còn script làm việc theo PHIẾU — hai cách đếm không bằng nhau (đo
được: 21 phiếu Bến Cam còn mở đang mang cờ đã in, trong khi cột hiện 18 đơn). Thay vào đó
dùng trần an toàn SO_PHIEU_TOI_DA.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> --no-http < bin/reset_wrong_printed_pick_slips.py
"""

CHI_XEM = False  # True = chỉ liệt kê, không ghi gì.

# Chỉ xử lý phiếu của kho này (mã kho). None = mọi kho. Đặt 'KBC' vì cột đang xử lý là của
# kho Bến Cam — phiếu kho khác (VD TSN/PICK/17987) không liên quan, reset kèm là sửa oan.
MA_KHO = 'KBC'

# Phiếu nào tính là "in sai" và cần đưa về chưa in:
#   'auto_thieu'    — CHỈ phiếu do HỆ THỐNG tự gửi in mà CÒN THIẾU hàng. Đây đúng là nhóm bị
#                     bug, và là mặc định. Phiếu người bấm in tay thì KHÔNG đụng: sale mở
#                     phiếu, xem "có gì giao nấy" rồi chủ động in là hành vi đúng thiết kế.
#   'auto_tat_ca'   — mọi phiếu hệ thống tự gửi, kể cả phiếu đã đủ hàng (auto in đúng).
#   'tat_ca_con_mo' — MỌI phiếu PICK còn mở đang mang cờ đã in, bất kể ai in. Chỉ dùng khi
#                     muốn dọn sạch cả cột, biết rõ là xoá cả dấu vết in tay hợp lệ.
CHE_DO = 'tat_ca_con_mo'

# Trần an toàn: chọn ra nhiều hơn số này thì DỪNG, không ghi. Không chốt bằng con số chính
# xác nữa (số phiếu đổi theo từng phút khi kho đang làm việc), nhưng vẫn phải có trần: nếu
# một sai sót ở bộ lọc làm nó quét ra hàng trăm phiếu thì phải dừng chứ không ghi tiếp.
SO_PHIEU_TOI_DA = 40

SEP = "=" * 100


def section(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


Picking = env['stock.picking'].sudo()  # noqa: F821

PICK_BASE = [
    ('picking_type_id.sequence_code', 'ilike', 'PICK'),
    ('return_id', '=', False),
]


def move_gap(picking):
    """Số dòng còn thiếu hàng của phiếu (dùng lại cách đo của code: quantity vs nhu cầu)."""
    gaps = []
    for move in picking.move_ids:
        if move.state == 'cancel':
            continue
        if (move.product_uom_qty or 0) - (move.quantity or 0) > 0.001:
            gaps.append(move)
    return gaps


section("1) Phiếu PICK CÒN MỞ mà mang cờ đã in — phân loại theo AI in và ĐỦ/THIẾU hàng")
kho_domain = [('picking_type_id.warehouse_id.code', '=ilike', MA_KHO)] if MA_KHO else []
con_mo_da_in = Picking.search(PICK_BASE + kho_domain + [
    ('state', 'not in', ('done', 'cancel')),
    ('x_printed', '=', True),
], order='id')
print(f"  Lọc kho: {MA_KHO or '(mọi kho)'}")
print(f"  Tổng phiếu còn mở mà mang cờ đã in: {len(con_mo_da_in)}\n")
print(f"  {'Phiếu':<22} {'Đơn':<20} {'state':<10} {'thiếu':<14} {'ai in':<16} {'sẽ sửa':<8} kho")
print(f"  {'-' * 110}")
nhom_a = Picking.browse()
phan_loai = {'auto_thieu': 0, 'auto_du': 0, 'tay_thieu': 0, 'tay_du': 0}
for pick in con_mo_da_in:
    so = pick.sale_id or pick.move_ids.sale_line_id.order_id[:1]
    gaps = move_gap(pick)
    is_auto = bool(pick.x_auto_print_requested)
    phan_loai['%s_%s' % ('auto' if is_auto else 'tay', 'thieu' if gaps else 'du')] += 1
    if CHE_DO == 'auto_thieu':
        chon = is_auto and bool(gaps)
    elif CHE_DO == 'auto_tat_ca':
        chon = is_auto
    else:
        chon = True
    if chon:
        nhom_a |= pick
    thieu = ('THIẾU %d dòng' % len(gaps)) if gaps else 'đủ hàng'
    wh = pick.picking_type_id.warehouse_id
    print(f"  {pick.name:<22} {(so.name or '-'):<20} {pick.state:<10} {thieu:<14} "
          f"{'HỆ THỐNG tự in' if is_auto else 'người bấm in':<16} "
          f"{'CÓ' if chon else '-':<8} {(wh.name or '-')[:20]}")

print(f"\n  Phân loại: hệ thống in + thiếu = {phan_loai['auto_thieu']}  |  "
      f"hệ thống in + đủ = {phan_loai['auto_du']}  |  "
      f"người in + thiếu = {phan_loai['tay_thieu']}  |  "
      f"người in + đủ = {phan_loai['tay_du']}")
print(f"  CHE_DO = {CHE_DO!r}  ->  sẽ sửa {len(nhom_a)} phiếu")

section("2) Nhóm (b) — phiếu PICK đã DONE mà đã in, đơn còn PACK đang mở: KHÔNG sửa")
done_printed = Picking.search(
    PICK_BASE + kho_domain + [('state', '=', 'done'), ('x_printed', '=', True)])
nhom_b = []
for pick in done_printed:
    so = pick.sale_id or pick.move_ids.sale_line_id.order_id[:1]
    if not so:
        continue
    con_pack_mo = any(
        p.picking_type_id.sequence_code == 'PACK' and p.state not in ('done', 'cancel')
        for p in so.picking_ids
    )
    if con_pack_mo:
        nhom_b.append((pick, so))
print(f"  Tìm thấy: {len(nhom_b)} phiếu (hàng đã lấy xong thật, chỉ chờ đóng gói)")
for pick, so in nhom_b[:20]:
    print(f"    {pick.name:<22} {so.name:<20} done lúc {pick.date_done}")
if nhom_b:
    print("\n  -> Muốn đưa cả nhóm này về 'chưa in' thì nói rõ, script hiện KHÔNG đụng tới nó:")
    print("     phiếu đã done nghĩa là kho ĐÃ lấy hàng xong, xoá cờ in là mất dấu vết việc đó.")

section("3) Đối chiếu")
print(f"  SẼ SỬA                   : {len(nhom_a)} phiếu  (CHE_DO = {CHE_DO!r})")
print(f"  Còn mở + đã in, giữ nguyên: {len(con_mo_da_in) - len(nhom_a)} phiếu")
print(f"  PICK done đã in, giữ nguyên: {len(nhom_b)} phiếu")
print("  Cột 'ĐÃ IN, CHỜ ĐÓNG GÓI' trên màn hình đếm theo ĐƠN, và chỉ đếm đơn CHƯA sang trạng")
print("  thái khác — đơn đã có shipper nhận, đã đóng gói đủ hoặc đã giao trong ngày rơi sang")
print("  cột khác dù phiếu vẫn mang cờ đã in. Nên con số màn hình nhỏ hơn tổng ở đây là bình")
print("  thường, không phải sai.")
don_lien_quan = set(
    (p.sale_id or p.move_ids.sale_line_id.order_id[:1]).id for p in nhom_a
) - {False}
print(f"  Số ĐƠN bị ảnh hưởng: {len(don_lien_quan)}")

trong_tran = len(nhom_a) <= SO_PHIEU_TOI_DA
print(f"  Trần an toàn {SO_PHIEU_TOI_DA} phiếu -> "
      f"{'trong trần, được ghi' if trong_tran else 'VƯỢT TRẦN, sẽ KHÔNG ghi'}")

if CHI_XEM:
    section("BƯỚC 1 — CHỈ XEM, chưa ghi gì")
    print("  Soát cột 'sẽ sửa' ở bảng phần 1 — chỉ những dòng đánh CÓ mới bị ghi.")
    print("  Đúng ý rồi thì mở file, đổi CHI_XEM = False rồi chạy lại để ghi.")
    print("  Muốn đổi phạm vi thì đổi CHE_DO hoặc MA_KHO.")
elif not nhom_a:
    section("Không có phiếu nào ở nhóm (a) — không ghi gì.")
elif not trong_tran:
    section("DỪNG — vượt trần an toàn, KHÔNG ghi gì")
    print(f"  Script chọn {len(nhom_a)} phiếu, vượt trần SO_PHIEU_TOI_DA = {SO_PHIEU_TOI_DA}.")
    print("  Con số này lớn bất thường so với một cột trên màn hình — xem lại danh sách phần 1")
    print("  và bộ lọc (MA_KHO, CHE_DO) trước khi nâng trần.")
else:
    section("4) ĐANG GHI — đưa nhóm (a) về chưa in")
    for pick in nhom_a:
        gaps = move_gap(pick)
        ly_do = ('phiếu còn thiếu %d dòng hàng' % len(gaps)) if gaps else 'phiếu chưa được lấy xong'
        pick.write({'x_printed': False, 'x_auto_print_requested': False})
        # Ghi chatter để sau này truy được vì sao cờ "đã in" biến mất — không im lặng sửa dữ liệu.
        pick.message_post(body=(
            'Đưa phiếu về trạng thái <b>CHƯA IN</b>: hệ thống đã tự động gửi in khi %s '
            '(lỗi auto-print tin vào trạng thái "Sẵn sàng" của phiếu, trong khi loại hoạt động '
            'là "Giao ngay khi có hàng" nên Sẵn sàng chỉ nghĩa là có một phần hàng). '
            'Giữ nguyên mốc thời gian in cũ để đối soát.' % ly_do
        ))
    env.cr.commit()  # noqa: F821
    print(f"  Đã ghi {len(nhom_a)} phiếu và commit.")

    section("5) Kiểm lại sau khi ghi")
    con_lai = Picking.search_count(PICK_BASE + [
        ('state', 'not in', ('done', 'cancel')),
        ('x_printed', '=', True),
    ])
    print(f"  Phiếu PICK còn mở mà vẫn mang cờ 'đã in': {con_lai} (mong đợi 0)")
    print("  Mở lại /sale_plan, cột 'ĐÃ IN, CHỜ ĐÓNG GÓI' phải giảm đúng số đơn ở phần 3.")
    print("  Snapshot của dashboard được đánh dấu dirty khi ghi lên phiếu (xem")
    print("  stock_picking._notify_delivery_planner_changed) nên cột tự cập nhật trong 1 phút;")
    print("  muốn thấy ngay thì chạy bin/force_refresh_snapshot.py.")
