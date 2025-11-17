# Hướng dẫn cài đặt Production Assembly & Disassembly Module

## Yêu cầu hệ thống

- Odoo 18.0
- Module `stock` (Inventory) đã được cài đặt
- Virtual Locations/Production với ID = 15 phải tồn tại

## Các bước cài đặt

### 1. Copy module vào thư mục addons

```bash
cp -r production_assembly /path/to/odoo/custom_addons/
```

### 2. Cập nhật danh sách modules

Trong Odoo:
1. Vào **Apps**
2. Nhấn **Update Apps List**
3. Tìm kiếm "Production Assembly"

### 3. Cài đặt module

1. Tìm module "Production Assembly & Disassembly"
2. Nhấn **Install**

### 4. Kiểm tra Virtual Location

Đảm bảo Virtual Locations/Production (ID=15) tồn tại:

1. Vào **Inventory > Configuration > Locations**
2. Tìm location có ID = 15
3. Nếu không tồn tại, tạo location mới với:
   - Name: "Virtual Locations/Production"
   - Usage: "Production"
   - Parent Location: "Virtual Locations"

### 5. Cấu hình quyền truy cập

Module tự động cấu hình quyền cho:
- **Stock User**: Tạo, xem, chỉnh sửa operations
- **Stock Manager**: Tất cả quyền bao gồm xóa

## Kiểm tra cài đặt

### 1. Kiểm tra menu

Sau khi cài đặt, bạn sẽ thấy menu mới:
**Inventory > Production Assembly**

### 2. Tạo operation đầu tiên

1. Vào **Inventory > Production Assembly > All Operations**
2. Nhấn **Create**
3. Chọn operation type và điền thông tin
4. Thêm component lines
5. Nhấn **Process Assembly/Disassembly**

### 3. Kiểm tra stock moves

Sau khi process operation, kiểm tra:
1. **Inventory > Reporting > Stock Moves**
2. Tìm moves có reference đến operation number

## Troubleshooting

### Lỗi "Virtual Production Location not found"

**Nguyên nhân**: Không tìm thấy location với ID = 15

**Giải pháp**:
1. Tạo location mới với usage = "Production"
2. Hoặc sửa code để sử dụng location khác

### Lỗi quyền truy cập

**Nguyên nhân**: User không có quyền Stock User/Manager

**Giải pháp**:
1. Vào **Settings > Users & Companies > Users**
2. Chỉnh sửa user
3. Thêm group "Inventory/User" hoặc "Inventory/Administrator"

### Module không xuất hiện trong Apps

**Nguyên nhân**: Module không được copy đúng vị trí

**Giải pháp**:
1. Kiểm tra đường dẫn addons trong config file
2. Restart Odoo server
3. Update Apps List

## Gỡ cài đặt

### 1. Uninstall module

1. Vào **Apps**
2. Tìm "Production Assembly & Disassembly"
3. Nhấn **Uninstall**

### 2. Xóa dữ liệu (nếu cần)

```sql
-- Xóa operations và related data
DELETE FROM production_operation_line;
DELETE FROM production_operation;
DELETE FROM ir_sequence WHERE code = 'production.operation';
```

**Lưu ý**: Backup database trước khi xóa dữ liệu!

## Hỗ trợ

Nếu gặp vấn đề, vui lòng:
1. Kiểm tra Odoo log files
2. Đảm bảo dependencies được cài đặt
3. Kiểm tra quyền truy cập file system
4. Liên hệ team phát triển