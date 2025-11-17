# Tóm tắt sửa lỗi - Production Assembly Module

## Ngày: 17/11/2025

### 🐛 Lỗi đã sửa

#### 1. AttributeError: 'production.operation' object has no attribute 'message_post'

**Mô tả lỗi:**
- Khi nhấn nút "Sản xuất" hoặc "Tháo gỡ", hệ thống báo lỗi AttributeError
- Nguyên nhân: Module không kế thừa từ mail.thread nhưng vẫn gọi method message_post()

**Giải pháp:**
- Xóa tất cả các lệnh gọi `message_post()` trong file `production_operation.py`
- Loại bỏ phần ghi log vào chatter vì module không cần chức năng này

**File thay đổi:**
- `models/production_operation.py`: Dòng 174-179 đã được xóa

#### 2. Cải tiến filter vị trí theo tồn kho

**Yêu cầu:**
- Khi chọn vị trí cho nguyên liệu sản xuất, chỉ hiển thị những vị trí mà sản phẩm được chọn có tồn kho

**Giải pháp thực hiện:**

1. **Thêm computed field `available_location_ids`:**
   - Tính toán động danh sách vị trí có tồn kho cho sản phẩm được chọn
   - Đối với sản xuất (assembly): chỉ hiển thị vị trí có `quantity > 0`
   - Đối với tháo gỡ (disassembly): hiển thị tất cả vị trí internal

2. **Cập nhật domain cho `source_location_id`:**
   ```python
   domain="[('usage', '=', 'internal'), ('id', 'in', available_location_ids)]"
   ```

3. **Cải tiến `_onchange_product_id`:**
   - Tự động chọn vị trí có tồn kho khi chọn sản phẩm
   - Ưu tiên vị trí có số lượng tồn kho lớn nhất

4. **Hiển thị số lượng tồn kho:**
   - Thêm cột "Có sẵn" trong danh sách thành phần
   - Giúp người dùng biết được số lượng tồn kho tại vị trí đã chọn

**File thay đổi:**
- `models/production_operation_line.py`: Thêm field và method mới
- `views/production_operation_views.xml`: Cập nhật hiển thị

### 🔧 Chi tiết kỹ thuật

#### Computed Field Logic:
```python
@api.depends('product_id', 'operation_type', 'company_id')
def _compute_available_location_ids(self):
    for line in self:
        if line.operation_type == 'assembly' and line.product_id:
            # Chỉ hiển thị vị trí có tồn kho
            quants = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('quantity', '>', 0),
                ('location_id.usage', '=', 'internal'),
                ('company_id', '=', line.company_id.id or self.env.company.id)
            ])
            line.available_location_ids = quants.mapped('location_id')
        else:
            # Tháo gỡ: hiển thị tất cả vị trí internal
            locations = self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('company_id', '=', line.company_id.id or self.env.company.id)
            ])
            line.available_location_ids = locations
```

### ✅ Kết quả

1. **Lỗi message_post đã được khắc phục hoàn toàn**
   - Không còn lỗi AttributeError khi thực hiện sản xuất/tháo gỡ
   - Module hoạt động ổn định

2. **Filter vị trí thông minh**
   - Chỉ hiển thị vị trí có tồn kho thực tế
   - Tự động chọn vị trí phù hợp khi chọn sản phẩm
   - Hiển thị số lượng tồn kho để người dùng tham khảo

3. **Trải nghiệm người dùng được cải thiện**
   - Giảm thiểu lỗi do chọn vị trí không có hàng
   - Thông tin tồn kho rõ ràng và trực quan
   - Quy trình làm việc mượt mà hơn

### 📋 Kiểm tra

Để kiểm tra các sửa đổi:

1. **Test lỗi message_post:**
   - Tạo một operation mới
   - Thêm component lines
   - Nhấn nút "Sản xuất" hoặc "Tháo gỡ"
   - Xác nhận không có lỗi AttributeError

2. **Test filter vị trí:**
   - Tạo operation type = "Sản xuất"
   - Chọn một sản phẩm trong component line
   - Kiểm tra dropdown "Vị trí nguồn" chỉ hiển thị vị trí có tồn kho
   - Xác nhận cột "Có sẵn" hiển thị đúng số lượng

### 🚀 Triển khai

Các thay đổi đã được commit và push lên branch `stagin`:
- Commit: `40df33d` - "Fix message_post bug and add location filter based on product stock"
- Repository: `hivongseth2/HLV-odoo-crm`
- Branch: `stagin`

Module sẵn sàng để cập nhật trên môi trường production.