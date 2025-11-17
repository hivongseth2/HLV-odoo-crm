# Production Assembly & Disassembly Module

Module Odoo 18 cho phép người dùng sản xuất hoặc tháo gỡ sản phẩm dựa trên các thành phần, sử dụng Virtual Locations/Production (id = 15), không cần dùng đầy đủ phân hệ MRP.

## Tính năng chính

### Sản xuất (Assembly)
- Nhập các thành phần để tạo ra thành phẩm
- Tự động tạo stock moves từ vị trí thành phần → Virtual Location → vị trí đích
- Cập nhật tồn kho tự động

### Tháo gỡ (Disassembly)  
- Tháo một thành phẩm thành các thành phần
- Tự động tạo stock moves từ vị trí thành phẩm → Virtual Location → vị trí thành phần
- Cập nhật tồn kho tự động

## Giao diện

### List View
Hiển thị danh sách các thao tác với:
- Số chứng từ
- Ngày
- Kiểu thao tác (Sản xuất/Tháo gỡ)
- Sản phẩm chính
- Số lượng
- Trạng thái (Nháp/Đã xử lý/Đã hủy)

### Form View
Màn hình chi tiết gồm:
- **Thông tin chung**: Kiểu thao tác, sản phẩm chính, số lượng, vị trí đích
- **Thành phần**: Danh sách các thành phần với số lượng và vị trí
- **Stock Moves**: Các chuyển kho được tạo tự động
- **Ghi chú**: Thông tin bổ sung

## Luồng nghiệp vụ

### Sản xuất (Assembly)
1. Chọn kiểu "Assembly (Production)"
2. Chọn sản phẩm cần sản xuất và số lượng
3. Chọn vị trí đích (nơi chứa thành phẩm sau khi sản xuất)
4. Thêm các thành phần:
   - Sản phẩm thành phần
   - Số lượng cần sử dụng
   - Vị trí hiện tại chứa thành phần
5. Nhấn "Process Assembly"

**Kết quả**: 
- Nguyên vật liệu bị trừ khỏi kho thực tế
- Thành phẩm được cộng vào vị trí đích

### Tháo gỡ (Disassembly)
1. Chọn kiểu "Disassembly"
2. Chọn sản phẩm cần tháo gỡ và số lượng
3. Chọn vị trí nguồn (nơi chứa sản phẩm cần tháo gỡ)
4. Thêm các thành phần:
   - Sản phẩm thành phần sau khi tháo gỡ
   - Số lượng tương ứng
   - Vị trí sẽ nhận thành phần
5. Nhấn "Process Disassembly"

**Kết quả**:
- Thành phẩm bị trừ khỏi kho
- Các thành phần được cộng về các vị trí được chọn

## Cài đặt

1. Copy module vào thư mục `custom_addons`
2. Cập nhật danh sách apps trong Odoo
3. Cài đặt module "Production Assembly & Disassembly"
4. Đảm bảo Virtual Locations/Production (id=15) tồn tại trong hệ thống

## Menu

Module tạo menu mới trong **Inventory > Production Assembly**:
- **All Operations**: Tất cả các thao tác
- **Assembly**: Chỉ các thao tác sản xuất
- **Disassembly**: Chỉ các thao tác tháo gỡ

## Quyền truy cập

- **Stock User**: Có thể tạo, xem và chỉnh sửa operations
- **Stock Manager**: Có thể xóa operations

## Lưu ý kỹ thuật

- Sử dụng Virtual Locations/Production (id=15) làm vị trí trung gian
- Tất cả stock moves được tạo tự động và xử lý ngay lập tức
- Không yêu cầu BoM (Bill of Materials) chuẩn
- Tích hợp hoàn toàn với hệ thống tồn kho Odoo
- Hỗ trợ tracking và traceability thông qua stock moves

## Phiên bản

- **Odoo Version**: 18.0
- **Module Version**: 1.0.0
- **License**: LGPL-3