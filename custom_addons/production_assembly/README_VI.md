# Module Sản xuất đơn giản - Odoo 18

## Tổng quan

Module này cung cấp một giao diện đơn giản cho các hoạt động kho/sản xuất, cho phép người dùng thực hiện hai loại thao tác chính:

- **Sản xuất (Assembly)**: Kết hợp các thành phần để tạo ra thành phẩm
- **Tháo gỡ (Disassembly)**: Tháo một thành phẩm thành các thành phần

Tất cả các thao tác đều sử dụng Virtual Locations/Production (id = 15) làm vị trí trung gian và dựa trên stock move mà không cần sử dụng đầy đủ phân hệ MRP.

## Tính năng chính

### Giao diện người dùng
- **Danh sách hoạt động**: Hiển thị số chứng từ, ngày, loại hoạt động, sản phẩm chính, số lượng và trạng thái
- **Form chi tiết**: Cho phép nhập thông tin hoạt động và danh sách thành phần
- **Giao diện tiếng Việt**: Toàn bộ interface đã được dịch sang tiếng Việt
- **Responsive design**: Tối ưu cho cả màn hình lớn và thiết bị di động

### Luồng nghiệp vụ

#### Sản xuất (Assembly)
1. Chọn loại hoạt động: **Sản xuất**
2. Chọn sản phẩm cần sản xuất và số lượng
3. Chọn vị trí đích (nơi lưu trữ thành phẩm)
4. Khai báo danh sách thành phần:
   - Sản phẩm thành phần
   - Số lượng cần sử dụng
   - Vị trí hiện tại của thành phần
5. Nhấn nút **Sản xuất**

**Kết quả**: 
- Nguyên vật liệu bị trừ khỏi kho thực tế
- Thành phẩm được cộng vào vị trí đích

#### Tháo gỡ (Disassembly)
1. Chọn loại hoạt động: **Tháo gỡ**
2. Chọn sản phẩm cần tháo gỡ và số lượng
3. Chọn vị trí nguồn (nơi chứa sản phẩm cần tháo)
4. Khai báo danh sách thành phần sau khi tháo:
   - Sản phẩm thành phần
   - Số lượng thu được
   - Vị trí sẽ nhận thành phần
5. Nhấn nút **Tháo gỡ**

**Kết quả**:
- Thành phẩm bị trừ khỏi kho
- Các thành phần được cộng về các vị trí được chọn

## Cài đặt

1. Copy module vào thư mục `addons` của Odoo
2. Cập nhật danh sách Apps trong Odoo
3. Tìm và cài đặt module "Production Assembly & Disassembly"

## Sử dụng

### Truy cập module
Vào menu: **Kho** → **Sản xuất đơn giản** → **Hoạt động**

### Tạo hoạt động mới
1. Nhấn nút **Tạo mới**
2. Chọn loại hoạt động (Sản xuất hoặc Tháo gỡ)
3. Điền thông tin sản phẩm chính và số lượng
4. Chọn vị trí phù hợp
5. Thêm các dòng thành phần
6. Nhấn nút thực hiện tương ứng

### Trạng thái hoạt động
- **Nháp**: Hoạt động mới tạo, có thể chỉnh sửa
- **Hoàn thành**: Hoạt động đã được thực hiện, không thể chỉnh sửa
- **Đã hủy**: Hoạt động đã bị hủy

## Cấu hình

### Virtual Location
Module sử dụng Virtual Locations/Production (id = 15) làm vị trí trung gian. Đảm bảo location này tồn tại trong hệ thống.

### Quyền truy cập
Module cung cấp các nhóm quyền:
- **User**: Có thể tạo và xem hoạt động
- **Manager**: Có thể quản lý tất cả hoạt động

## Lưu ý kỹ thuật

- Module không yêu cầu BoM (Bill of Materials) chuẩn
- Tất cả sản phẩm đều là `product.product` bình thường
- Tích hợp hoàn toàn với hệ thống kho của Odoo
- Tự động tạo stock moves và cập nhật tồn kho
- Không sử dụng mail.thread để tránh các tab không cần thiết

## Hỗ trợ

Để được hỗ trợ, vui lòng liên hệ:
- Website: https://hoanglongvu.com
- Email: support@hoanglongvu.com

## Phiên bản

- **Phiên bản**: 18.0.1.0.0
- **Tương thích**: Odoo 18.0
- **Giấy phép**: LGPL-3