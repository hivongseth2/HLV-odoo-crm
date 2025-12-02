# WordPress Price Sync Configuration Guide

## Tổng Quan
Module `wordpress_sync` cho phép đồng bộ giá sản phẩm từ Odoo lên WordPress tự động hoặc thủ công.

## Cách Cấu Hình

### 1. Lưu Credentials vào System Parameters

Để lưu WordPress API credentials an toàn, module sử dụng **System Parameters** của Odoo.

#### Cách 1: Qua UI (Dễ nhất)

1. Vào **Website > WordPress Sync > WordPress Configuration**
2. Click **Create** để tạo config mới
3. Nhập:
   - **Config Name**: Tên của cấu hình (vd: "Main Store", "Test Store")
   - **WordPress Domain**: Domain WordPress (vd: `https://hoanglongvu.com` - **KHÔNG** có dấu `/` ở cuối)
   - **Consumer Key**: API Consumer Key từ WordPress
   - **Consumer Secret**: API Consumer Secret từ WordPress
   - **Cache Purge URL** (optional): Endpoint để xóa cache LiteSpeed
   - **Keep Sync Logs (Days)**: Số ngày lưu log (mặc định 30 ngày)

4. Click **Save**
5. Click **Test Connection** để kiểm tra kết nối

#### Cách 2: Qua System Parameters (Nâng cao)

Nếu muốn lưu credentials thủ công:

1. Vào **Settings > Technical > System Parameters**
2. Tạo 2 parameters:
   - **Key**: `wordpress_sync.Main_Store.wc_key`
     **Value**: Consumer Key từ WordPress

   - **Key**: `wordpress_sync.Main_Store.wc_secret`
     **Value**: Consumer Secret từ WordPress

   (Thay `Main_Store` bằng tên config của bạn)

3. Sau đó vào **WordPress Configuration** và chỉ cần nhập:
   - Config Name: `Main_Store`
   - WordPress Domain: `https://hoanglongvu.com`
   - Các field khác

---

## Cách Hoạt Động

### Auto-Sync (Tự động)
Khi bạn chỉnh sửa giá sản phẩm trong Odoo:
1. Nhập giá vào field `x_studio_ga_web` (regular price) hoặc `x_studio_gi_bn_thng_mi` (sale price)
2. Click **Save**
3. Hệ thống tự động:
   - Tìm sản phẩm trên WordPress qua SKU
   - Cập nhật giá trên WordPress
   - Tạo note bên trong sản phẩm với chi tiết thay đổi
   - Log vào **Price Sync History**
   - Xóa cache WordPress (nếu có)

### Manual Sync (Thủ công)
1. Vào sản phẩm, click nút **🔄 Sync to WordPress**
2. Chọn:
   - **Single Product**: Đồng bộ sản phẩm hiện tại
   - **All Products**: Đồng bộ tất cả sản phẩm có SKU
3. Click **Sync Now**

---

## Trường Giá

| Trường | Mô Tả | Dùng Cho |
|--------|-------|---------|
| `x_studio_ga_web` | Giá bán lẻ | Regular Price (WordPress) |
| `x_studio_gi_bn_thng_mi` | Giá thương mại | Sale Price (WordPress) |

**Logic Sale Price:**
- Nếu `x_studio_gi_bn_thng_mi` > 0 và < `x_studio_ga_web` → Set sale price trên WordPress
- Nếu không → Xóa sale price trên WordPress

---

## Xem Lịch Sử Đồng Bộ

1. Vào **Website > WordPress Sync > Price Sync History**
2. Xem tất cả các lần sync:
   - **Status**: success ✅, failed ❌, skipped ⏭️
   - **Message**: Chi tiết lỗi hoặc kết quả
   - **Changed by**: Người thực hiện
   - **Sync Date**: Thời gian

---

## Kiểm Tra Bên Trong Sản Phẩm

Mỗi khi sync thành công, bên trong product sẽ có note:
```
🔄 WordPress Sync:
Regular Price: 100,000
Sale Price: 80,000
Synced by: [Username]
Date: 02/12/2025 14:30:00
```

---

## Lỗi Thường Gặp

| Lỗi | Nguyên Nhân | Giải Pháp |
|-----|------------|----------|
| "Credentials Missing" | Credentials chưa được lưu | Vào Config, nhập Consumer Key/Secret, Save |
| "Product not found" | SKU không tồn tại trên WordPress | Check SKU trên WordPress có giống không |
| "HTTP 401" | Consumer Key/Secret sai | Kiểm tra lại credentials |
| "Invalid regular price" | Giá regular <= 0 | Nhập giá regular > 0 |

---

## Bảo Mật

- **Credentials được lưu trong System Parameters** của Odoo, không lưu trong database của module
- Trường `wc_key` và `wc_secret` hiển thị dạng **password** (ẩn ký tự)
- Chỉ user có quyền truy cập System Parameters mới có thể xem/chỉnh sửa credentials

---

## Hỗ Trợ

Nếu gặp lỗi, kiểm tra:
1. **Logs**: Vào Settings > Technical > Logs
2. **Sync History**: Xem chi tiết thất bại
3. **Product Notes**: Xem bên trong sản phẩm
4. **System Parameters**: Kiểm tra credentials có đúng không
