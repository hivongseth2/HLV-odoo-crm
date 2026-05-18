# -*- coding: utf-8 -*-
"""
check_order_log.py
==================
Kiểm tra toàn bộ log / chatter của đơn hàng DH125524949231713
(hoặc bất kỳ đơn hàng nào qua ORDER_NAME bên dưới)

Chạy bằng lệnh:
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_order_log.py

Nội dung kiểm tra:
  A) Sale Order: trạng thái, ngày, khách hàng, tổng tiền
  B) Toàn bộ pickings liên quan + trạng thái
  C) Toàn bộ messages/chatter của sale order
  D) Toàn bộ messages/chatter của từng picking
  E) Tóm tắt: có video hay không, giai đoạn nào bị vướng
"""

ORDER_NAME = "DH125524949231713"    # <-- đổi nếu cần
MAX_MSG = 30                        # số message in tối đa mỗi record

SEP  = "=" * 72
SEP2 = "-" * 72

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

def sub(title):
    print(f"\n  {SEP2}\n  {title}\n  {SEP2}")

# ─────────────────────────────────────────────
# A. Sale Order
# ─────────────────────────────────────────────
section(f"A. SALE ORDER: {ORDER_NAME}")

sale = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if not sale:
    # Thử tìm khác (Shopee / custom prefix)
    tail = ORDER_NAME[-12:] if len(ORDER_NAME) > 12 else ORDER_NAME
    sale = env['sale.order'].sudo().search([('name', 'ilike', tail)], limit=5)
    if sale:
        print(f"  ⚠️  Không match exact, tìm tương tự:")
        for s in sale:
            print(f"    id={s.id}  name={s.name}  state={s.state}  partner={s.partner_id.name}")
        sale = sale[0]  # lấy cái đầu để tiếp tục
        print(f"\n  → Dùng: {sale.name} (id={sale.id})")
    else:
        print(f"  ❌ Không tìm thấy sale order '{ORDER_NAME}'")
        sale = None

if sale:
    print(f"  name         : {sale.name}")
    print(f"  state        : {sale.state}")
    print(f"  date_order   : {sale.date_order}")
    print(f"  partner      : {sale.partner_id.name}")
    print(f"  amount_total : {sale.amount_total:,.0f} {sale.currency_id.name}")
    print(f"  origin       : {sale.origin or 'N/A'}")
    print(f"  user         : {sale.user_id.name}")
    print(f"  team         : {sale.team_id.name if sale.team_id else 'N/A'}")

# ─────────────────────────────────────────────
# B. Pickings liên quan
# ─────────────────────────────────────────────
section("B. PICKINGS LIÊN QUAN")

if sale:
    pickings = env['stock.picking'].sudo().search([('sale_id', '=', sale.id)])
else:
    pickings = env['stock.picking'].sudo().search([
        '|', '|',
        ('name', 'ilike', ORDER_NAME),
        ('origin', 'ilike', ORDER_NAME),
        ('group_id.name', 'ilike', ORDER_NAME),
    ], limit=30)

if not pickings:
    print(f"  ❌ Không tìm thấy picking nào")
else:
    print(f"  Tổng số picking: {len(pickings)}\n")
    # Sort theo type + date
    for p in pickings.sorted(lambda x: (x.picking_type_id.sequence_code or '', x.scheduled_date or '')):
        has_video = bool(p.message_ids.filtered(
            lambda m: 'drive.google.com' in (m.body or '') or '📹' in (m.body or '')
        ))
        video_flag = "✅ VIDEO" if has_video else "❌ no video"
        print(f"  [{p.picking_type_id.sequence_code:6}] {p.name:30} state={p.state:12} {video_flag}")
        print(f"           scheduled={p.scheduled_date}  done={p.date_done}")

# ─────────────────────────────────────────────
# C. Chatter của Sale Order
# ─────────────────────────────────────────────
if sale:
    section("C. CHATTER SALE ORDER")
    msgs = sale.message_ids.sorted('date', reverse=True)[:MAX_MSG]
    if not msgs:
        print("  (không có messages)")
    for m in msgs:
        author = (m.author_id.name or 'System') if m.author_id else 'System'
        body = (m.body or '').replace('\n', ' ')[:160]
        print(f"  [{m.date}] [{m.message_type:12}] {author[:20]:20} | {body}")

# ─────────────────────────────────────────────
# D. Chatter từng picking
# ─────────────────────────────────────────────
section("D. CHATTER TỪNG PICKING")

for p in pickings.sorted(lambda x: (x.picking_type_id.sequence_code or '', x.scheduled_date or '')):
    sub(f"{p.name}  [{p.picking_type_id.sequence_code}]  state={p.state}")
    print(f"  location: {p.location_id.complete_name} → {p.location_dest_id.complete_name}")
    
    # Thông tin pack
    if hasattr(p, 'x_pack_start_time'):
        print(f"  x_pack_start_time     : {p.x_pack_start_time}")
    if hasattr(p, 'x_pack_actual_duration'):
        print(f"  x_pack_actual_duration: {p.x_pack_actual_duration} phút")

    msgs = p.message_ids.sorted('date', reverse=True)[:MAX_MSG]
    if not msgs:
        print("  (không có messages)")
        continue
    
    print(f"\n  --- {len(p.message_ids)} messages total (hiện {len(msgs)} gần nhất) ---")
    for m in msgs:
        author = (m.author_id.name or 'System') if m.author_id else 'System'
        body = (m.body or '').replace('\n', ' ').strip()

        # Highlight video messages
        is_video = 'drive.google.com' in body or '📹' in body or 'Video' in body
        flag = "  🎬 VIDEO" if is_video else ""
        
        print(f"  [{m.date}] [{m.message_type:12}] {author[:22]:22} |{flag}")
        if body:
            # In body dài hơn nếu là video
            limit = 400 if is_video else 180
            print(f"    {body[:limit]}")

# ─────────────────────────────────────────────
# E. Tóm tắt
# ─────────────────────────────────────────────
section("E. TÓM TẮT")

if pickings:
    pack_pickings = pickings.filtered(
        lambda p: p.picking_type_id.sequence_code and 
        ('PACK' in p.picking_type_id.sequence_code.upper() or 
         'OUT' in p.picking_type_id.sequence_code.upper())
    )
    
    if not pack_pickings:
        print(f"  ⚠️  Không có picking loại PACK/OUT → chưa có giai đoạn đóng gói → bình thường không có video")
    else:
        for p in pack_pickings:
            has_video = bool(p.message_ids.filtered(
                lambda m: 'drive.google.com' in (m.body or '') or '📹' in (m.body or '')
            ))
            print(f"\n  Picking PACK: {p.name}  state={p.state}")
            if has_video:
                vms = p.message_ids.filtered(lambda m: 'drive.google.com' in (m.body or '') or '📹' in (m.body or ''))
                print(f"  ✅ Đã có video – link trong message:")
                for vm in vms:
                    print(f"     {vm.body[:300]}")
            else:
                print(f"  ❌ CHƯA CÓ VIDEO")
                print(f"  Nguyên nhân có thể:")
                if p.state not in ('done', 'assigned', 'in_progress'):
                    print(f"    → Picking chưa ở trạng thái ready/in-progress/done (state={p.state})")
                if not p.x_pack_start_time if hasattr(p, 'x_pack_start_time') else False:
                    print(f"    → x_pack_start_time trống: chưa vào giao diện đóng gói")
                print(f"    → Chạy script bin/debug_video_upload.py để kiểm tra GDrive config")
                print(f"    → Tìm 'BG_UPLOAD' trong odoo-server.log để xem lỗi exception")

print(f"\n  LỆNH TÌM LOG SERVER (chạy trên máy chủ):")
print(f"    grep -i 'BG_UPLOAD\\|FINISH_UPLOAD\\|START_UPLOAD\\|UPLOAD_CHUNK' /var/log/odoo/odoo-server.log | tail -100")
print(f"    grep -i 'BG_UPLOAD fatal\\|BG_UPLOAD missing' /var/log/odoo/odoo-server.log | tail -50")

print(f"\n{SEP}")
print("  SCRIPT HOÀN THÀNH")
print(SEP)
