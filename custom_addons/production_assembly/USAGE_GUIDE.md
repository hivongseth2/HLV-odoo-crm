# Hướng dẫn sử dụng Module Production Assembly

## Tổng quan
Module Production Assembly cho phép người dùng thực hiện sản xuất và tháo gỡ sản phẩm một cách đơn giản mà không cần sử dụng đầy đủ phân hệ MRP của Odoo.

## Cài đặt

### 1. Cài đặt module
1. Đảm bảo module đã được đặt trong thư mục `custom_addons`
2. Vào Apps → Update Apps List
3. Tìm kiếm "Production Assembly"
4. Click Install

### 2. Cấu hình ban đầu
Module sẽ tự động:
- Tạo sequence cho số chứng từ
- Thiết lập quyền truy cập cơ bản
- Load dữ liệu demo (nếu được bật)

## Sử dụng

### Truy cập module
Inventory → Operations → Production Assembly

### Tạo chứng từ sản xuất (Assembly)

1. **Tạo mới**: Click "Create" 
2. **Chọn thông tin cơ bản**:
   - Operation Type: Assembly
   - Main Product: Sản phẩm cần sản xuất
   - Quantity: Số lượng cần sản xuất
   - Destination Location: Vị trí sẽ nhận thành phẩm

3. **Thêm thành phần**:
   - Trong tab "Components", click "Add a line"
   - Chọn Product: Nguyên vật liệu/thành phần
   - Nhập Quantity: Số lượng cần sử dụng
   - Chọn Source Location: Vị trí hiện tại của nguyên vật liệu

4. **Xử lý**: Click "Process Assembly"

### Tạo chứng từ tháo gỡ (Disassembly)

1. **Tạo mới**: Click "Create"
2. **Chọn thông tin cơ bản**:
   - Operation Type: Disassembly
   - Main Product: Sản phẩm cần tháo gỡ
   - Quantity: Số lượng cần tháo
   - Source Location: Vị trí hiện tại của sản phẩm

3. **Thêm thành phần nhận được**:
   - Trong tab "Components", click "Add a line"
   - Chọn Product: Thành phần sẽ nhận được
   - Nhập Quantity: Số lượng sẽ nhận
   - Chọn Destination Location: Vị trí sẽ chứa thành phần

4. **Xử lý**: Click "Process Disassembly"

## Luồng nghiệp vụ

### Sản xuất (Assembly)
```
Nguyên vật liệu (Kho A) → Virtual Location (ID=15) → Thành phẩm (Kho B)
```

### Tháo gỡ (Disassembly)  
```
Thành phẩm (Kho A) → Virtual Location (ID=15) → Thành phần (Kho B, C, D...)
```

## Trạng thái chứng từ

- **Draft**: Nháp - có thể chỉnh sửa
- **Done**: Đã xử lý - không thể chỉnh sửa
- **Cancel**: Đã hủy

## Tính năng nâng cao

### Theo dõi Stock Moves
- Tab "Stock Moves" hiển thị tất cả chuyển động kho được tạo
- Có thể theo dõi chi tiết quá trình di chuyển hàng hóa

### Chatter & Activities
- Hỗ trợ ghi chú và theo dõi hoạt động
- Tự động ghi log khi thay đổi trạng thái

### Demo Data
Module bao gồm dữ liệu demo:
- 2 chứng từ sản xuất mẫu
- 1 chứng từ tháo gỡ mẫu
- Các sản phẩm và thành phần mẫu

## Lưu ý quan trọng

1. **Virtual Location**: Module sử dụng Virtual Locations/Production (ID=15) làm vị trí trung gian
2. **Không cần BoM**: Không bắt buộc phải có Bill of Materials, linh hoạt khai báo thành phần
3. **Tích hợp Inventory**: Tất cả thao tác đều cập nhật tồn kho thực tế
4. **Quyền truy cập**: Cần quyền Inventory User để sử dụng

## Khắc phục sự cố

### Lỗi cài đặt
- Đảm bảo module 'stock' và 'mail' đã được cài đặt
- Kiểm tra quyền truy cập thư mục

### Lỗi xử lý
- Kiểm tra tồn kho tại vị trí nguồn
- Đảm bảo các vị trí đã được tạo và có quyền truy cập

### Lỗi hiển thị
- Refresh browser cache
- Kiểm tra quyền truy cập của user

## Hỗ trợ
Liên hệ HLV Development Team để được hỗ trợ kỹ thuật.