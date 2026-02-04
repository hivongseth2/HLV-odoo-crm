"""
Hướng dẫn kiểm tra và fix

BƯỚC 1: UPGRADE MODULE (QUAN TRỌNG!)
====================================
Vào Odoo → Apps → tìm "Zalo Chat Integration"
→ Click "Upgrade" hoặc chạy lệnh:

./odoo-bin -u zalo_chat_integration -d your_database --stop-after-init

BƯỚC 2: XÓA PARTNERS CŨ
========================
Vào Settings > Technical > Database Structure > Models > res.partner
Tìm partners có zalo_user_id, xóa đi (để test lại từ đầu)

BƯỚC 3: TEST TẠO MỚI
=====================
1. Nhắn tin mới từ Zalo OA
2. Check log:
   - "Fetching user info from Zalo API for new user..." 
   - "Downloaded avatar from https://..."
   - "Created partner for Zalo user: [TÊN] (ID: [ID])"

3. Vào Partners > tìm theo tên Zalo user
   - Kiểm tra có avatar không (field image_1920)

BƯỚC 4: DEBUG NẾU VẪN LỖI
==========================
Chạy trong Odoo shell (Debug mode):

conv_id = 1  # ID của conversation
conv = env['zalo.chat.conversation'].browse(conv_id)
user_info = conv._fetch_zalo_user_info(conv.zalo_user_id)
print("User info:", user_info)

# Test download avatar
if user_info.get('avatar'):
    avatar = conv._download_avatar(user_info['avatar'])
    print("Avatar downloaded:", len(avatar) if avatar else None)

BƯỚC 5: KIỂM TRA LỖI MEMBER
============================
Lỗi "Không thể thêm nhiều thành viên" có thể do:

1. Code cũ vẫn trong cache → UPGRADE MODULE
2. Module khác hook vào mail.message → Check:
   
   grep -r "channel_member_ids" custom_addons/
   grep -r "_action_add_members" custom_addons/

KỊCH BẢN TỰ ĐỘNG CẬP NHẬT PARTNERS CŨ
======================================
Chạy trong Odoo Python shell:

convs = env['zalo.chat.conversation'].search([])
for conv in convs:
    if not conv.partner_id or not conv.partner_id.image_1920:
        print(f"Updating {conv.id}...")
        user_info = conv._fetch_zalo_user_info(conv.zalo_user_id)
        if user_info:
            partner = conv._get_or_create_partner(conv.zalo_user_id, user_info)
            conv.partner_id = partner.id
            print(f"  → Partner: {partner.name}, has avatar: {bool(partner.image_1920)}")
"""
pass
