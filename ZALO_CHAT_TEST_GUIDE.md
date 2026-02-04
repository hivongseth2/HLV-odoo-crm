# Hướng dẫn Test Zalo Chat Integration

## Bước 1: Cập nhật code
```bash
git pull
```

## Bước 2: Upgrade module
- Vào Apps → tìm "Zalo Chat Integration"
- Click **Upgrade**
- Hoặc chạy: `./odoo-bin -u zalo_chat_integration -d your_db --stop-after-init`

## Bước 3: Restart Odoo
- Restart server để load code mới

## Bước 4: Xóa channels cũ (nếu có)
- Vào Discuss → Xóa các channel Zalo cũ
- Hoặc vào Settings > Technical > Discuss Channels → Xóa

## Bước 5: Test các tính năng

### Test 1: Nhận tin từ Zalo
1. Gửi tin nhắn từ Zalo OA
2. Check log xem có lỗi không
3. Kiểm tra:
   - ✅ Tin nhắn hiện trong Discuss
   - ✅ Avatar hiển thị đúng
   - ✅ Tên có prefix "Zalo:"
   - ✅ Không có HTML tags

### Test 2: Typing notification
1. Mở channel Zalo trong Discuss
2. Gõ chữ (chưa gửi)
3. Check log:
   - ✅ KHÔNG có warning "Không thể thêm nhiều thành viên"
   - ✅ Typing indicator hoạt động

### Test 3: Gửi tin từ Odoo
1. Gõ tin trong Discuss channel
2. Nhấn Enter
3. Check:
   - ✅ Tin gửi đi thành công
   - ✅ User Zalo nhận được (không có HTML tags)
   - ✅ Không có lỗi member warning

## Các Fix đã thực hiện

### Fix 1: Avatar & User Info
- ✅ Download avatar từ Zalo API
- ✅ Tạo partner với tên thật từ Zalo
- ✅ Set avatar cho channel

### Fix 2: Strip HTML tags
- ✅ Loại bỏ `<p>`, `<em>` trước khi gửi Zalo
- ✅ Chỉ gửi plain text

### Fix 3: Member limit error
- ✅ Override `write()` để chặn thêm member
- ✅ Override `notify_typing()` để skip nếu không phải member
- ✅ Override `message_post()` để post as system nếu cần

### Fix 4: OA send event
- ✅ Support event `oa_send_text`
- ✅ Skip sync to discuss cho outbound OA messages

## Nếu vẫn có lỗi

### Lỗi typing warning
- Check file `discuss_channel.py` đã load chưa
- Check `__init__.py` có import `discuss_channel` chưa
- Thử xóa channel và tạo lại

### Tin nhắn không hiện
- Check `skip_discuss_sync` được initialize chưa
- Check log webhook có lỗi không
- Xem conversation có partner_id chưa

### Avatar không hiện
- Check partner có `image_128` chưa
- Xem log có "Downloaded avatar from..." không
- API Zalo cần scope `user.detail`
