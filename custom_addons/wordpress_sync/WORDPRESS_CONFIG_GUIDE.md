# Hướng Dẫn Cấu Hình WordPress Price Sync

## Tổng Quan

Module `wordpress_sync` đồng bộ giá sản phẩm từ Odoo lên WordPress/WooCommerce.

**Lưu ý quan trọng:**
- Module này **CHỈ** đồng bộ **giá** từ Odoo lên WordPress
- **KHÔNG** đồng bộ ngược từ WordPress về Odoo
- **KHÔNG** đồng bộ sản phẩm mới, chỉ cập nhật giá sản phẩm đã có

---

## Bước 1: Lấy WooCommerce API Keys

Trên WordPress Admin:

1. Vào **WooCommerce > Settings > Advanced > REST API**
2. Click **Add key**
3. Điền thông tin:
   - **Description**: `Odoo Price Sync`
   - **User**: Chọn admin user
   - **Permissions**: **Read/Write**
4. Click **Generate API key**
5. **Copy ngay** Consumer Key và Consumer Secret (chỉ hiện 1 lần)

---

## Bước 2: Tạo Cấu Hình WordPress trong Odoo

1. Vào **Inventory > Configuration > WordPress Sync > Cấu hình WooCommerce**
2. Click **Create**
3. Điền thông tin:

| Field | Giá trị | Ví dụ |
|-------|---------|-------|
| Tên cấu hình | Tên để nhận biết | `Store chính` |
| WordPress Domain | URL WordPress (KHÔNG có `/` cuối) | `https://hoanglongvu.com` |
| Consumer Key | Key từ WooCommerce | `ck_xxxxx` |
| Consumer Secret | Secret từ WooCommerce | `cs_xxxxx` |
| Cache Purge URL | (Tùy chọn) LiteSpeed cache | `/wp-json/litespeed/v1/purge?type=product&sku=` |
| Giữ log (ngày) | Số ngày lưu log | `30` |

4. Click **Save**
5. Click **Test kết nối** để kiểm tra

**Kết quả mong đợi:** Thông báo "Kết nối thành công"

---

## Bước 3: Bật Đồng Bộ Tự Động

1. Vào **Settings > Inventory**
2. Trong phần **Products**, tìm **Đồng bộ giá WordPress**
3. Tick checkbox để bật
4. Chọn cấu hình WordPress vừa tạo
5. Click **Save**

---

## Cách Hoạt Động

### Đồng Bộ Tự Động

**Điều kiện:** Checkbox "Đồng bộ giá WordPress" đã bật

| Hành động | Kết quả |
|-----------|---------|
| Tick checkbox | Chỉ bật chế độ theo dõi, **KHÔNG** sync giá hiện tại |
| Sửa giá sản phẩm | Tự động sync sản phẩm đó lên WordPress |
| Sửa sản phẩm không có SKU | Bỏ qua, không sync |

**Field giá được theo dõi:**
- `x_studio_ga_web` → Regular Price trên WordPress
- `x_studio_gi_bn_thng_mi` → Sale Price trên WordPress

### Đồng Bộ Thủ Công

**Hoạt động bất kể checkbox bật hay tắt**

1. Vào form sản phẩm
2. Click nút **Đồng bộ giá WordPress** (trong button box)
3. Chọn chế độ:
   - **Một sản phẩm**: Sync sản phẩm hiện tại
   - **Tất cả sản phẩm**: Sync tất cả sản phẩm có SKU
4. Chọn cấu hình WordPress
5. Click **Đồng bộ**

---

## Logic Xử Lý Giá

| Điều kiện | Kết quả trên WordPress |
|-----------|------------------------|
| `x_studio_ga_web` > 0 | Set Regular Price |
| `x_studio_gi_bn_thng_mi` > 0 VÀ < `x_studio_ga_web` | Set Sale Price |
| `x_studio_gi_bn_thng_mi` = 0 hoặc >= `x_studio_ga_web` | Xóa Sale Price |
| Sản phẩm không có SKU | Bỏ qua |
| SKU không tồn tại trên WordPress | Báo lỗi "Product not found" |

---

## Xem Lịch Sử Đồng Bộ

1. Vào **Inventory > Configuration > WordPress Sync > Lịch sử đồng bộ**
2. Xem các lần sync với trạng thái:
   - **success** (xanh): Thành công
   - **failed** (đỏ): Thất bại
   - **skipped** (vàng): Bỏ qua

3. Click vào record để xem chi tiết:
   - Giá cũ → Giá mới
   - Message lỗi (nếu có)
   - Người thực hiện

---

## Internal Note Trên Sản Phẩm

Mỗi lần sync thành công, sản phẩm sẽ có note trong chatter:

```
WordPress Sync:
Regular Price: 100,000
Sale Price: 80,000
Synced by: Admin
Date: 03/12/2025 10:30:00
```

---

## Lỗi Thường Gặp

| Lỗi | Nguyên nhân | Giải pháp |
|-----|-------------|-----------|
| "Thiếu Credentials" | Chưa nhập Consumer Key/Secret | Vào cấu hình, nhập key/secret, Save |
| "Kết nối thất bại HTTP 401" | Key/Secret sai | Tạo lại API key trên WooCommerce |
| "Product not found on WooCommerce" | SKU không tồn tại trên WordPress | Kiểm tra SKU trên WordPress |
| "Invalid regular price" | Giá `x_studio_ga_web` <= 0 | Nhập giá > 0 |
| "Timeout" | Server WordPress chậm | Thử lại sau |

---

## Bảo Mật

- Consumer Key/Secret được lưu trong **System Parameters** (không lưu trực tiếp trong model)
- Hiển thị dạng password (ẩn ký tự) trên UI
- Chỉ user có quyền Admin mới truy cập được cấu hình

---

## Lưu Ý Quan Trọng

1. **Sản phẩm phải có SKU** (`default_code` trong Odoo) để sync được
2. **SKU phải trùng khớp** giữa Odoo và WordPress
3. **Không sync hàng loạt khi tick checkbox** - chỉ sync khi có thay đổi giá
4. **Test trước khi dùng production** - test với 1 sản phẩm trước

---

## Hỗ Trợ

Nếu gặp lỗi:
1. Kiểm tra **Lịch sử đồng bộ** để xem message lỗi chi tiết
2. Kiểm tra **Chatter sản phẩm** để xem note sync
3. Dùng **Test kết nối** để verify API hoạt động
4. Kiểm tra Odoo server log nếu cần debug sâu hơn
