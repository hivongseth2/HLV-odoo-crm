# HLV Barcode Shipper - Hướng Dẫn Sử Dụng

## 📱 Module Quét Mã Vạch Cho Shipper

Module này giúp shipper sử dụng điện thoại để quét mã phiếu pick và xử lý phiếu giao hàng (OUT) tương ứng.

## 🚀 Cách Cài Đặt

1. **Cài đặt module:**
   - Vào Apps → tìm "HLV Barcode Shipper" 
   - Click Install

2. **Phân quyền:**
   - Vào Settings → Users & Companies → Users
   - Chọn user shipper → tab Access Rights
   - Thêm group "Shipper" hoặc "Shipper Manager"

## 🎯 Cách Sử Dụng

### 📍 Truy Cập Giao Diện

**Có 3 cách để truy cập:**

1. **Từ Menu Odoo:**
   - Đăng nhập Odoo → Menu "Shipper Scanner" → "📱 Barcode Scanner"

2. **Truy cập trực tiếp:**
   - Mở trình duyệt → nhập: `https://your-odoo-domain.com/barcode/shipper`
   - Ví dụ: `https://your-company.odoo.com/barcode/shipper`

3. **Từ ứng dụng mobile:**
   - Tạo bookmark/shortcut đến URL trên

### 📋 Quy Trình Làm Việc

#### **Bước 1: Quét Mã PICK**
1. Mở giao diện scanner
2. Quét mã phiếu PICK (ví dụ: PICK00001)
3. Hệ thống tự động tìm phiếu OUT liên quan
4. Hiển thị thông tin đơn hàng và danh sách kiện/sản phẩm

#### **Bước 2: Quét Từng Kiện/Sản phẩm**
1. Quét từng mã PACK (ví dụ: PACK00001) hoặc mã sản phẩm
2. Mỗi item được quét sẽ chuyển sang màu xanh ✅
3. Thanh tiến độ hiển thị % hoàn thành

#### **Bước 3: Hoàn Tất Giao Hàng**
1. **Cách 1:** Khi quét đủ tất cả → nút "🚚 Hoàn Tất Giao Hàng" xuất hiện
2. **Cách 2:** Quét lại mã PICK để hoàn tất trực tiếp
3. Hệ thống gọi `picking.button_validate()` → chuyển phiếu OUT sang DONE

## 🔧 Tính Năng

### ✅ Giao Diện Mobile-First
- Thiết kế responsive, tối ưu cho điện thoại
- CSS chuyên nghiệp, không ảnh hưởng giao diện Odoo khác
- Hỗ trợ cả portrait và landscape

### ✅ API Endpoints
- `POST /scan_pick` - Quét mã PICK
- `GET /get_out/<pick_name>` - Lấy thông tin phiếu OUT
- `POST /scan_package` - Quét mã kiện/sản phẩm  
- `POST /complete_out` - Hoàn tất giao hàng

### ✅ Quản Lý & Báo Cáo
- **Scan Logs:** Ghi lại tất cả hoạt động quét mã
- **Delivery Orders:** Xem danh sách phiếu giao hàng
- **User Management:** Quản lý quyền shipper

### ✅ Bảo Mật
- Phân quyền theo nhóm: Shipper, Shipper Manager
- Chỉ shipper mới truy cập được giao diện
- Log đầy đủ hoạt động để audit

## 📊 Menu & Quyền

### 👤 Shipper (Nhân viên giao hàng)
- **📱 Barcode Scanner:** Giao diện quét mã chính
- **📦 Delivery Orders:** Xem phiếu giao hàng của mình

### 👨‍💼 Shipper Manager (Quản lý)
- **📊 Management:** Quản lý tổng thể
  - **📋 Scan Logs:** Xem log quét mã của tất cả shipper
  - **📦 All Pickings:** Xem tất cả phiếu pick/out
- **⚙️ Settings:** Cài đặt hệ thống
  - **👥 Shipper Users:** Quản lý user shipper

## 🎨 Thiết Kế CSS

CSS được thiết kế **chuyên nghiệp và tối giản:**

- ✅ **Scoped CSS:** Chỉ áp dụng cho module này (`.hlv-barcode-shipper`)
- ✅ **Không màu mè:** Sử dụng màu sắc Bootstrap chuẩn
- ✅ **Professional:** Thiết kế clean, dễ sử dụng
- ✅ **Mobile-first:** Tối ưu cho thiết bị di động
- ✅ **Accessibility:** Hỗ trợ focus, keyboard navigation

## 🔍 Troubleshooting

### ❌ Không tìm thấy phiếu OUT
- Kiểm tra phiếu PICK có tồn tại không
- Đảm bảo có phiếu OUT liên quan (cùng sale order/group)
- Phiếu OUT phải ở trạng thái "Ready" hoặc "Partially Available"

### ❌ Không quét được mã
- Kiểm tra camera có hoạt động không
- Đảm bảo có đủ ánh sáng
- Thử nhập mã thủ công

### ❌ Không có quyền truy cập
- Kiểm tra user có group "Shipper" không
- Đảm bảo module đã được cài đặt đúng

## 🔗 API Documentation

### Scan PICK Order
```bash
POST /scan_pick
Content-Type: application/json

{
    "barcode": "PICK00001"
}
```

### Get OUT Order Info  
```bash
GET /get_out/PICK00001
```

### Scan Package/Product
```bash
POST /scan_package
Content-Type: application/json

{
    "out_id": 123,
    "barcode": "PACK00001"
}
```

### Complete Delivery
```bash
POST /complete_out
Content-Type: application/json

{
    "out_id": 123
}
```

## 📞 Hỗ Trợ

Nếu gặp vấn đề, vui lòng:
1. Kiểm tra Scan Logs để xem lỗi chi tiết
2. Đảm bảo quyền truy cập đúng
3. Liên hệ admin hệ thống

---

**Phiên bản:** 1.0.0  
**Tương thích:** Odoo 18.0  
**Tác giả:** HLV Team