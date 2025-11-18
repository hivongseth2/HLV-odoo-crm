# HLV Barcode Shipper Module

## Mô tả
Module Odoo 18 cho phép shipper sử dụng điện thoại để quét mã vạch và xử lý phiếu giao hàng một cách hiệu quả.

## Tính năng chính

### 🔍 Quét mã PICK
- Shipper quét mã phiếu PICK (PICKxxxxx)
- Hệ thống tự động tìm phiếu OUT liên quan
- Hiển thị thông tin đơn hàng và khách hàng

### 📦 Quét kiện hàng
- Hiển thị danh sách kiện hàng (PACKxxx) hoặc sản phẩm
- Theo dõi trạng thái quét của từng kiện (scanned = true/false)
- Thanh tiến độ hiển thị số kiện đã quét

### ✅ Hoàn tất giao hàng
- Nút "Hoàn tất giao hàng" xuất hiện khi quét đủ kiện
- Tự động gọi picking.button_validate() để DONE phiếu OUT
- Có thể quét lại mã PICK để hoàn tất nhanh

### 📱 Giao diện di động
- Tối ưu cho điện thoại và tablet
- Hỗ trợ quét bằng camera hoặc nhập thủ công
- Giao diện thân thiện với người dùng

## Cài đặt

1. Copy module vào thư mục `custom_addons`
2. Cập nhật danh sách module trong Odoo
3. Cài đặt module "HLV Barcode Shipper"
4. Cấu hình quyền người dùng

## Cấu hình quyền

### Nhóm Shipper
- Quyền quét mã vạch và xử lý phiếu giao hàng
- Chỉ xem được phiếu OUT ở trạng thái sẵn sàng
- Không thể tạo/xóa phiếu

### Nhóm Shipper Manager
- Tất cả quyền của Shipper
- Xem được tất cả log quét mã
- Quản lý người dùng shipper

## Sử dụng

### Bước 1: Truy cập giao diện
- Vào menu "Shipper Scanner" > "📱 Mobile Scanner"
- Hoặc truy cập trực tiếp: `/barcode/shipper`

### Bước 2: Quét mã PICK
1. Nhập hoặc quét mã phiếu PICK (ví dụ: PICK00001)
2. Hệ thống tìm phiếu OUT liên quan
3. Hiển thị thông tin đơn hàng

### Bước 3: Quét kiện hàng
1. Quét từng kiện hàng (PACKxxx) hoặc sản phẩm
2. Theo dõi tiến độ trên thanh progress
3. Kiện đã quét sẽ có dấu ✅

### Bước 4: Hoàn tất
1. Khi quét đủ kiện, nhấn "Hoàn tất giao hàng"
2. Hoặc quét lại mã PICK để hoàn tất nhanh
3. Phiếu OUT sẽ chuyển sang trạng thái DONE

## API Endpoints

### POST /api/barcode/scan_pick
Quét mã phiếu PICK
```json
{
    "barcode": "PICK00001"
}
```

### POST /api/barcode/get_out
Lấy thông tin phiếu OUT
```json
{
    "picking_id": 123
}
```

### POST /api/barcode/scan_package
Quét kiện hàng/sản phẩm
```json
{
    "picking_id": 123,
    "barcode": "PACK001"
}
```

### POST /api/barcode/complete_out
Hoàn tất giao hàng
```json
{
    "picking_id": 123
}
```

### POST /api/barcode/scan_history
Xem lịch sử quét
```json
{
    "picking_id": 123,
    "limit": 50
}
```

## Cấu trúc Module

```
hlv_barcode_shipper/
├── __init__.py
├── __manifest__.py
├── README.md
├── controllers/
│   ├── __init__.py
│   └── barcode_controller.py
├── models/
│   ├── __init__.py
│   ├── barcode_scan_log.py
│   ├── stock_picking.py
│   └── stock_package_level.py
├── security/
│   ├── security.xml
│   └── ir.model.access.csv
├── static/src/
│   ├── css/
│   │   └── barcode_shipper.css
│   └── js/
│       ├── barcode_scanner.js
│       └── sw.js
└── views/
    ├── barcode_shipper_views.xml
    ├── barcode_scan_log_views.xml
    ├── stock_picking_views.xml
    └── menu_views.xml
```

## Models

### barcode.scan.log
- Ghi log tất cả hoạt động quét mã
- Theo dõi người dùng, thời gian, trạng thái
- Hỗ trợ audit trail

### stock.picking (extend)
- Thêm trường shipper_scanned, shipper_scan_time
- Tính toán số kiện đã quét
- Phương thức tìm phiếu OUT từ PICK

### stock.package.level (extend)
- Thêm trường scanned, scan_time
- Theo dõi trạng thái quét của từng kiện

### stock.move.line (extend)
- Thêm trường scanned cho sản phẩm
- Hỗ trợ quét sản phẩm khi không có kiện

## Bảo mật

- Sử dụng CSRF protection cho API
- Kiểm tra quyền truy cập cho mọi endpoint
- Record rules hạn chế dữ liệu theo nhóm người dùng
- Log tất cả hoạt động quét mã

## Tương thích

- Odoo 18.0+
- Hỗ trợ mobile browsers
- Tương thích với module stock chuẩn
- Không xung đột với module barcode có sẵn

## Hỗ trợ

Liên hệ: HLV Development Team
Website: https://hoanglongvu.com

## License

LGPL-3