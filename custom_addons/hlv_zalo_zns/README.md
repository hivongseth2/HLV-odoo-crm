# HLV Zalo ZNS & Stock Notification Module

Module tích hợp Zalo Official Account (OA) cho Odoo, hỗ trợ 2 chức năng chính:

1. **ZNS (Zalo Notification Service)** - Gửi tin nhắn ZNS cho khách hàng
2. **Stock Notification** - Gửi thông báo nội bộ cho nhân viên khi xuất/nhập kho

---

## 🌟 Tính năng mới: Shared Token Manager (v1.1.0)

### ✅ Lợi ích
- **Quản lý tập trung:** Chỉ cần authorize 1 lần, tất cả chức năng đều dùng được
- **Đồng bộ tự động:** Token được refresh tự động, không lo hết hạn
- **Dễ bảo trì:** Token lưu ở 1 nơi duy nhất, không cần cập nhật nhiều chỗ

### 📦 Cấu hình nhanh

#### Bước 1: Tạo Shared Token Manager
```
Zalo > 🔑 Shared Token > Create
- Name: HLV Zalo OA Token
- App ID: [Từ Zalo Developer Portal]
- Secret Key: [Từ Zalo Developer Portal]
- Callback URL: https://your-domain.com/hlv_zalo/shared/oauth/callback
- Active: ✅
```

#### Bước 2: Authorize
- Click **"Authorize with Zalo"**
- Login và authorize
- Click **"Test Token"** để kiểm tra

#### Bước 3: Cấu hình ZNS
```
Zalo > ZNS Config
- Use Shared Token: ✅ (Recommended)
- Template ID: [ZNS Template ID]
```

#### Bước 4: Cấu hình Stock Notification
```
Inventory > Configuration > Zalo Stock Notification
- Use Shared Token: ✅ (Recommended)
- Send on Incoming: ✅
- Send on Outgoing: ✅
- Online Recipient User ID: [Zalo User ID kế toán online]
- Offline Recipient User ID: [Zalo User ID kế toán offline]
- Incoming Recipient User ID: [Zalo User ID kế toán nhập kho]
```

---

## 📋 Hướng dẫn chi tiết

### ZNS - Gửi tin cho khách hàng

**Tự động gửi khi:**
- Phiếu xuất kho (stock.picking) hoàn tất

**Gửi thủ công trong code:**
```python
zns_config = self.env['hlv.zalo.zns'].search([('use_shared_token', '=', True)], limit=1)
params = {
    'customer_name': 'Nguyễn Văn A',
    'order_code': 'SO001',
    'amount': '1,000,000',
}
result = zns_config.send_zns('0987654321', params)
```

### Stock Notification - Gửi tin nội bộ

**Tự động gửi khi:**
- Validate phiếu xuất kho → Gửi tới kế toán online/offline (dựa vào mã saler)
- Validate phiếu nhập kho → Gửi tới kế toán nhập kho

**Logic XUẤT KHO:**
1. Lấy mã saler từ `sale.order.x_studio_misa_saler_code`
2. Nếu mã trong danh sách online → Gửi tới kế toán online
3. Nếu không → Gửi tới kế toán offline

**Logic NHẬP KHO:**
- Tất cả phiếu nhập từ supplier → Gửi tới kế toán nhập kho
- Bỏ qua chuyển kho nội bộ

---

## 🔄 Migration từ token riêng

Nếu bạn đang dùng phiên bản cũ (token riêng):

1. **Upgrade module:**
   ```bash
   odoo-bin -u hlv_zalo_zns -d your_database
   ```

2. **Tạo Shared Token Manager** (như hướng dẫn trên)

3. **Cập nhật config:**
   - ZNS Config: Bật "Use Shared Token"
   - Stock Notification Config: Bật "Use Shared Token"

4. **Test lại chức năng**

Chi tiết xem [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md)

---

## 🐛 Troubleshooting

### "No active Zalo Shared Token found"
→ Tạo Shared Token Manager và authorize

### "Token invalid"
→ Vào Shared Token Manager, click "Refresh Token"

### Stock Notification không gửi
→ Kiểm tra:
- Config active chưa
- send_on_incoming/outgoing đã bật chưa
- User ID có đúng không
- User đã follow OA chưa

### Logs
```bash
grep "Zalo" /var/log/odoo/odoo-server.log
```

---

## 📄 License

LGPL-3

---

> **Lưu ý:** Endpoint và payload có thể thay đổi theo phiên bản API của Zalo. Hãy đối chiếu tài liệu chính thức để điều chỉnh nếu cần.
