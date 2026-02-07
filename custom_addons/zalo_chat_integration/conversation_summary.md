# Zalo Chat Integration - Debugging & Optimization Summary

## 1. Trạng thái hiện tại (Current Status)
- **Odoo Version**: 18.0
- **Module**: `zalo_chat_integration`
- **Tính năng chính**:
    - Webhook nhận tin nhắn Zalo -> tạo LiveChat Session.
    - Gửi tin nhắn từ Odoo Discuss -> Zalo user.
    - GPT Integration (Tóm tắt, Tạo báo giá, Phân tích).
- **Vấn đề đang xử lý**: 
    - Tin nhắn gửi từ giao diện Discuss không đi qua Zalo API (mặc dù log Odoo báo thành công `/mail/message/post`).
    - Hook `mail.message.create` dường như không được kích hoạt khi gửi từ UI Chat trong Odoo 18.

## 2. Các vấn đề đã giải quyết (Resolved Issues)

### A. Odoo 18 Compatibility
1. **Removed `_strip_html`**:
    - **Lỗi**: `AttributeError: 'mail.message' object has no attribute '_strip_html'`
    - **Nguyên nhân**: Method `_strip_html` đã bị loại bỏ trong Odoo 18.
    - **Giải pháp**: Thay thế bằng `odoo.tools.html2plaintext(html_content)`.
    - **Files updated**: `models/discuss_channel.py`, `models/mail_message.py`.

2. **Missing Dependencies**:
    - **Lỗi**: `AttributeError: '_unknown' object has no attribute 'id'` khi truy cập `sale_order_id`.
    - **Nguyên nhân**: Module phụ thuộc vào model `sale.order` nhưng thiếu `depends: ['sale']` trong manifest.
    - **Giải pháp**: Thêm `'sale'` vào `__manifest__.py`.

3. **Field Cleanups**:
    - Loại bỏ trường thừa `livechat_channel_id` trong `zalo.chat.evaluation` gây nhầm lẫn và lỗi.

### B. Message Sending Logic (Ongoing Debugging)
- **Triệu chứng**: Gửi tin nhắn từ UI Chat, log server có request `POST /mail/message/post` nhưng không thấy log debug của module Zalo.
- **Giả thuyết**: Odoo 18 Discuss App sử dụng cơ chế mới (Bus/Controller) để post message, bỏ qua hoặc gọi `create` theo cách khác khiến `@api.model_create_multi` trên `mail.message` không bắt được (hoặc bị bypass).
- **Hành động**:
    - Đã thử revert về commit cũ (f440df13) được cho là hoạt động -> Vẫn fail (có thể do môi trường Odoo 18 khác biệt).
    - Đã chuyển logic intercept sang `discuss.channel.message_post()`.
    - Thêm logging chi tiết (`[ZALO DEBUG]`) để trace luồng đi của tin nhắn.

## 3. Workflow & Architecture

### Luồng Gửi Tin Nhắn (Outbound Code Flow)
1. **User Action**: Nhập tin nhắn và nhấn Enter trên giao diện Discuss.
2. **Odoo Action**: Gọi controller `/mail/message/post` hoặc method `message_post` của channel.
3. **Intercept Logic** (Hiện tại đang cài đặt trong `discuss_channel.py`):
    - Override `message_post` của `discuss.channel`.
    - Kiểm tra loại channel `channel_type == 'livechat'`.
    - Kiểm tra `livechat_channel_id` có liên kết với Config Zalo OA không.
    - Xác định người nhận (Target Partner) trong channel (loại trừ người gửi).
    - Tìm `zalo.chat.conversation` tương ứng với Target Partner.
    - Tạo `zalo.chat.message`.
    - Gọi `action_send()` để bắn API qua Zalo.

### Luồng Nhận Tin Nhắn (Inbound Webhook)
1. **Zalo Webhook** -> Controller Odoo.
2. Tìm/Tạo Partner dựa trên Zalo User ID.
3. Tìm/Tạo `discuss.channel` (LiveChat Session).
4. `message_post` nội dung vào channel (có context `skip_zalo_sync=True` để tránh gửi ngược lại).

## 4. Next Steps
1. **Kiểm tra Log mới**: Xem output của `[ZALO DEBUG]` trong `discuss.channel.message_post` để xác nhận method này có được gọi không.
2. **Nếu method được gọi**: Debug logic tìm kiếm Conversation/Partner bên trong đó.
3. **Nếu method KHÔNG được gọi**: Cần tìm hiểu cơ chế override `_message_post_after_hook` hoặc các method khác của `mail.thread` trong Odoo 18.
