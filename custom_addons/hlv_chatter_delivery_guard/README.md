# HLV Chatter & Delivery Guard

Addon này cung cấp hai lớp bảo vệ:

- Không cho xóa `mail.message` đã gắn với chatter của chứng từ/liên hệ. Tin nhắn Discuss không bị ảnh hưởng.
- Thêm cờ **Không được xuất hàng** trên liên hệ. Cờ có hiệu lực với chính liên hệ đó và toàn bộ cây liên hệ con.

Các phiếu có loại hoạt động `outgoing`, hoặc mã trình tự chứa `PICK`, `PACK`, `OUT`, `SHIP`, `DELIVERY`, sẽ bị chặn ở cả lúc giữ hàng, xác nhận và hoàn tất. Phiếu khách trả hàng ngược vào kho không bị chặn.

## Cài đặt

Cập nhật Apps List, tìm **HLV Chatter & Delivery Guard** và cài đặt, hoặc chạy:

```bash
odoo-bin -d <database> -i hlv_chatter_delivery_guard --stop-after-init
```
