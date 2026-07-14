# HLV Chatter & Delivery Guard

Addon này cung cấp hai lớp bảo vệ:

- Mặc định không cho xóa riêng `mail.message` trong chatter. Người dùng thuộc nhóm **HLV Chatter / Xóa tin nhắn chatter** được phép xóa từng tin nhắn bình luận.
- Khi xóa cả chứng từ/đơn/phiếu, toàn bộ chatter đi kèm vẫn được xóa bình thường; rule chỉ chặn xóa message riêng lẻ. Tin nhắn Discuss không bị ảnh hưởng.
- Thêm cờ **Không được xuất hàng** trên liên hệ. Cờ có hiệu lực với chính liên hệ đó và toàn bộ cây liên hệ con.

Các phiếu có loại hoạt động `outgoing`, hoặc mã trình tự chứa `PICK`, `PACK`, `OUT`, `SHIP`, `DELIVERY`, sẽ bị chặn ở cả lúc giữ hàng, xác nhận và hoàn tất. Phiếu khách trả hàng ngược vào kho không bị chặn.

## Cài đặt

Cập nhật Apps List, tìm **HLV Chatter & Delivery Guard** và cài đặt, hoặc chạy:

```bash
odoo-bin -d <database> -i hlv_chatter_delivery_guard --stop-after-init
```
