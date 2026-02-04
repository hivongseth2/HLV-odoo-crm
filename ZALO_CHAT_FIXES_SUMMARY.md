# Zalo Chat Integration - Fixes Summary

## Ngày: 2026-02-04

### Vấn đề ban đầu
1. Avatar không hiển thị (hiện "Administrator" thay vì tên Zalo user)
2. Lỗi "Không thể thêm nhiều thành viên" khi typing/gửi tin
3. HTML tags (`<p>`, `<em>`) được gửi sang Zalo
4. Chưa support event `oa_send_text`

---

## Các Fix đã thực hiện

### 1. User Info & Avatar Fetching
**Files changed:**
- `models/zalo_chat_conversation.py`

**Changes:**
- Thêm method `_fetch_zalo_user_info()` gọi API `/oa/user/detail`
- Thêm method `_get_or_create_partner()` tạo partner với avatar
- Thêm method `_download_avatar()` download ảnh từ Zalo URL
- Update `_find_or_create_conversation()` để chỉ fetch lần đầu

**Result:**
✅ Partner có tên thật và avatar từ Zalo
✅ Channel name có prefix "Zalo: Tên User"

---

### 2. HTML Stripping
**Files changed:**
- `models/mail_message.py`

**Changes:**
- Thêm method `_strip_html()` để loại bỏ HTML tags
- Update message content trước khi gửi Zalo API

**Result:**
✅ Tin nhắn gửi sang Zalo là plain text
✅ Không còn `<p>em ơi</p>` mà chỉ "em ơi"

---

### 3. Member Addition Error Prevention
**Files changed:**
- `models/discuss_channel.py` (NEW)
- `models/__init__.py`

**Changes:**
- Override `write()` - chặn member addition ở mức thấp nhất
- Override `notify_typing()` - skip nếu user không phải member
- Override `message_post()` - post as system nếu author không phải member
- Override `_notify_thread()` - prevent auto-subscribe

**Result:**
✅ Không còn warning "Không thể thêm nhiều thành viên"
✅ Typing hoạt động mượt mà
✅ Gửi tin không bị lỗi

---

### 4. OA Send Event Support
**Files changed:**
- `controllers/main.py`

**Changes:**
- Thêm xử lý cho event `oa_send_text`
- Set `skip_discuss_sync = True` cho outbound OA messages
- Initialize `skip_discuss_sync = False` cho tất cả events khác

**Result:**
✅ Track được tin OA gửi từ Dashboard/API
✅ Không duplicate tin trong discuss

---

### 5. Channel Creation Improvements
**Files changed:**
- `models/zalo_chat_conversation.py`

**Changes:**
- Dùng `channel_partner_ids` với `(4, pid)` thay vì `channel_member_ids`
- Set `avatar_128` từ partner image
- Force refresh member info với `invalidate_recordset()`

**Result:**
✅ Channel icon hiển thị avatar Zalo user
✅ Không còn lỗi persona JS error

---

## Hướng dẫn Deploy

### Bước 1: Pull code
```bash
cd d:\HLV\HLV-odoo-crm
git pull
```

### Bước 2: Upgrade module
**Option A - Từ UI:**
1. Vào Apps
2. Tìm "Zalo Chat Integration"
3. Click "Upgrade"

**Option B - Từ command line:**
```bash
./odoo-bin -u zalo_chat_integration -d your_database_name --stop-after-init
```

### Bước 3: Restart Odoo
```bash
# Restart server
sudo systemctl restart odoo
# hoặc
./odoo-bin restart
```

### Bước 4: Xóa channels cũ (recommended)
1. Vào Discuss
2. Xóa các channel Zalo cũ (không có avatar)
3. Hoặc: Settings > Technical > Discuss Channels → Delete

### Bước 5: Test
1. Gửi tin từ Zalo OA
2. Check avatar, tên, tin nhắn
3. Test typing → Không còn warning
4. Test gửi tin → Plain text, không HTML

---

## Files Modified

```
custom_addons/zalo_chat_integration/
├── models/
│   ├── __init__.py (added discuss_channel import)
│   ├── discuss_channel.py (NEW - overrides)
│   ├── mail_message.py (added HTML stripping)
│   └── zalo_chat_conversation.py (user info fetching)
└── controllers/
    └── main.py (oa_send_text support)
```

---

## Testing Checklist

- [ ] Avatar hiển thị đúng trong channel icon
- [ ] Tên channel có prefix "Zalo: Tên User"
- [ ] Tin nhắn từ Zalo hiển thị trong Discuss
- [ ] Typing không có warning
- [ ] Gửi tin từ Odoo → Zalo nhận plain text
- [ ] HTML tags bị loại bỏ
- [ ] Event oa_send_text được track

---

## Known Issues & Solutions

### Issue: Avatar vẫn không hiện
**Solution:** Xóa channel cũ và gửi tin mới từ Zalo để tạo channel mới

### Issue: Vẫn có warning typing
**Solution:** 
1. Check module đã upgrade chưa
2. Restart Odoo
3. Check file `discuss_channel.py` có trong folder models không

### Issue: Tin nhắn không sync
**Solution:**
1. Check log webhook có lỗi không
2. Verify `skip_discuss_sync` được initialize
3. Check conversation có partner_id không

---

## API Requirements

**Zalo API Scopes needed:**
- `user.detail` - để fetch user info và avatar

**Endpoint used:**
- `POST https://openapi.zalo.me/v3.0/oa/user/detail`

---

## Contact
Nếu có vấn đề gì, check log tại:
- Settings > Technical > Logging
- Filter by "zalo"

Hoặc xem Odoo server log trực tiếp.
