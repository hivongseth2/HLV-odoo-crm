# Warehouse Access Control & Location Filtering

## Tổng quan

Module Production Assembly đã được nâng cấp với hệ thống kiểm soát truy cập kho và lọc vị trí thông minh, giúp quản lý quyền truy cập của người dùng đến các kho và vị trí cụ thể.

## Tính năng mới

### 1. Warehouse Access Configuration (Cấu hình phân quyền kho)

#### Mô tả
- Cho phép quản trị viên cấu hình quyền truy cập của từng người dùng đến các kho và vị trí cụ thể
- Mỗi người dùng chỉ có thể có một cấu hình duy nhất
- Hỗ trợ phân quyền theo kho (warehouse) và vị trí (location)

#### Cách sử dụng
1. Vào menu **Sản xuất đơn giản > Cấu hình > Phân quyền kho**
2. Tạo mới hoặc chỉnh sửa cấu hình cho người dùng
3. Chọn người dùng và các kho/vị trí mà họ được phép truy cập

#### Các trường thông tin
- **Người dùng**: Người dùng được phân quyền
- **Kho được phép**: Danh sách các kho mà người dùng có thể truy cập
- **Vị trí được phép**: Danh sách các vị trí mà người dùng có thể truy cập

### 2. Disassembly Location Filtering (Lọc vị trí cho tháo gỡ)

#### Mô tả
- Thêm trường "Vị trí nguồn" riêng cho hoạt động tháo gỡ
- Tự động lọc chỉ hiển thị các vị trí có tồn kho của sản phẩm chính
- Áp dụng kiểm soát truy cập theo cấu hình phân quyền

#### Cách hoạt động
1. Khi tạo hoạt động tháo gỡ, chọn sản phẩm chính
2. Trường "Vị trí nguồn" sẽ chỉ hiển thị các vị trí:
   - Có tồn kho của sản phẩm chính > 0
   - Người dùng hiện tại có quyền truy cập (theo cấu hình)
3. Khi thực hiện tháo gỡ, sản phẩm chính sẽ được lấy từ vị trí nguồn này

### 3. Enhanced Component Location Filtering (Lọc vị trí thành phần nâng cao)

#### Mô tả
- Áp dụng kiểm soát truy cập cho việc chọn vị trí trong dòng thành phần
- Kết hợp lọc theo tồn kho và quyền truy cập của người dùng

#### Cách hoạt động
- **Sản xuất (Assembly)**: Chỉ hiển thị vị trí có tồn kho của thành phần và người dùng có quyền truy cập
- **Tháo gỡ (Disassembly)**: Hiển thị tất cả vị trí mà người dùng có quyền truy cập

## Luồng nghiệp vụ

### Sản xuất với kiểm soát truy cập
1. Người dùng tạo hoạt động sản xuất
2. Chọn sản phẩm chính và vị trí đích (nếu có quyền)
3. Thêm dòng thành phần:
   - Chọn sản phẩm thành phần
   - Chọn vị trí nguồn (chỉ hiển thị vị trí có tồn kho và có quyền truy cập)
4. Thực hiện sản xuất

### Tháo gỡ với lọc vị trí thông minh
1. Người dùng tạo hoạt động tháo gỡ
2. Chọn sản phẩm chính
3. Chọn vị trí nguồn (chỉ hiển thị vị trí có tồn kho của sản phẩm chính)
4. Thêm dòng thành phần với vị trí đích (theo quyền truy cập)
5. Thực hiện tháo gỡ

## Cấu hình và bảo mật

### Quyền truy cập
- **Stock User**: Có thể xem cấu hình phân quyền
- **Stock Manager**: Có thể tạo, sửa, xóa cấu hình phân quyền

### Ràng buộc dữ liệu
- Mỗi người dùng chỉ có thể có một cấu hình phân quyền
- Không thể tạo cấu hình trùng lặp cho cùng một người dùng

## Demo Data

Module cung cấp demo data bao gồm:
- Cấu hình phân quyền mẫu cho admin
- Sản phẩm demo (thành phẩm và thành phần)
- Tồn kho mẫu
- Hoạt động sản xuất và tháo gỡ mẫu

## Testing

Chạy test để kiểm tra tính năng:
```bash
odoo-bin -d your_database -i production_assembly --test-enable --stop-after-init
```

Hoặc chạy test cụ thể:
```bash
odoo-bin -d your_database --test-tags production_assembly --stop-after-init
```

## Lưu ý kỹ thuật

### Database Changes
- Thêm model `warehouse.access.config`
- Thêm field `source_location_id` vào `production.operation`
- Thêm computed field `available_source_location_ids`
- Cập nhật logic lọc vị trí trong `production.operation.line`

### Performance
- Sử dụng computed field với store=False để tránh tải database
- Áp dụng domain filter trực tiếp trong view để giảm tải server
- Cache kết quả lọc vị trí trong session

### Compatibility
- Tương thích với Odoo 18.0
- Không ảnh hưởng đến dữ liệu hiện có
- Có thể nâng cấp từ phiên bản cũ mà không mất dữ liệu