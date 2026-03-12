# Module Công cụ Giới hạn Số lượng Dòng Chuyển kho

## Tổng quan
Module này ngăn chặn người dùng nhập số lượng giữ tồn (quantity) vượt quá số lượng tồn thực tế tại vị trí trong kho. 

**Vấn đề giải quyết:** Khi user nhập 3 cái nhưng hệ thống tự động nhảy thành 2 dòng (3 + 1 = 4), module này sẽ ngăn chặn bằng cách:
1. Chỉ cho phép dành riêng số lượng có sẵn trong move hiện tại
2. Không tính tồn kho từ các moves khác
3. Tự động điều chỉnh về mức khả dụng

## Tính Năng
✅ **Kiểm tra Real-time**: Thông báo ngay khi user cố gắng nhập vượt quá tồn kho  
✅ **Tự động điều chỉnh**: Giới hạn số lượng đến mức khả dụng  
✅ **Ràng buộc Database**: Ngăn lưu dữ liệu không hợp lệ qua API hoặc bulk operations  
✅ **Chỉ áp dụng Kho Nội bộ**: Bỏ qua warehouse, supplier, customer locations  
✅ **Tính toán Chính xác**: Chỉ tính số lượng đã dành riêng trong move hiện tại

## Cách Hoạt động

### 1. Khi User Thay đổi Số lượng (UI)
```
Bước 1: User nhập số lượng
Bước 2: Module kiểm tra:
        - Tồn kho thực tế: 3 cái
        - Số đã dành riêng khác (trong move này): 0 cái
        - Còn có sẵn: 3 cái
Bước 3: Nếu nhập > 3, hiển thị popup cảnh báo
Bước 4: Tự động điều chỉnh xuống 3 cái
```

### 2. Khi Lưu Record
- Ràng buộc `_check_quantity_not_exceed_stock` kiểm tra lại
- Nếu dữ liệu không hợp lệ, ngăn lưu và hiển thị lỗi

### 3. Các Hàm Tính toán
| Hàm | Mục đích |
|-----|---------|
| `_get_total_stock_at_location()` | Lấy tồn kho thực tế tại vị trí |
| `_get_reserved_qty_in_move()` | Lấy số lượng đã dành riêng khác trong move này |

## Cách Cài đặt

1. **Copy module vào:**  
   `custom_addons/stock_move_line_quantity_limit/`

2. **Cập nhật Apps List trong Odoo:**
   - Vào Settings > Apps > Update Apps List

3. **Cài đặt Module:**
   - Tìm "Công cụ Giới hạn Số lượng Dòng Chuyển kho"
   - Nhấn **Install**

4. **Restart Odoo** để hoàn tất

## So Sánh: Code Gốc vs Module

| Tính Năng | Code Gốc | Module |
|-----------|----------|--------|
| @api.onchange | ✅ | ✅ Cải tiến |
| @api.constrains | ❌ | ✅ Có |
| Tính reserved qty trong move | ❌ | ✅ Chính xác |
| Xử lý moves done/cancel | ❌ | ✅ Có |
| Tiếng Việt | ❌ | ✅ Đầy đủ |
| Warning popup | ✅ | ✅ Chi tiết |

## Các Tình huống Được Xử lý

### ✅ Được Kiểm soát
- Nhập số lượng vào draft moves
- Chỉnh sửa số lượng trên dòng chuyển kho
- API calls cố gắng set số lượng không hợp lệ
- Bulk operations

### ❌ Không Kiểm soát
- Moves ở trạng thái "done" (hoàn thành)
- Moves ở trạng thái "cancel" (hủy)
- Kho không phải loại "internal" (supplier, customer, etc)
- Sản phẩm không xác định

## Ví dụ Sử dụng

### Tình huống 1: Nhập vượt quá trong UI
```
Tồn kho thực tế: 3 cái
User nhập: 5 cái
Kết quả: 
  • Hiển thị cảnh báo
  • Tự động điều chỉnh thành 3 cái
```

### Tình huống 2: Qua API
```python
# Python ORM - sẽ raise ValidationError
move_line = env['stock.move.line'].create({
    'product_id': 123,
    'quantity': 100,  # Vượt quá
    'location_id': 456,
})
# → ValidationError: Không thể dành riêng 100 cái...
```

### Tình huống 3: Không bị kiểm soát
```
• Move ở trạng thái done → Không kiểm tra
• Location là supplier warehouse → Không kiểm tra
• Sản phẩm không xác định → Không kiểm tra
```

## Messages & Thông báo

### Cảnh báo Real-time (onchange)
```
Tiêu đề: Vượt quá tồn kho!
Nội dung: Bạn cố gắng dành riêng X cái, nhưng chỉ còn Y cái khả dụng.
          Hệ thống đã tự động điều chỉnh thành Y cái.
```

### Lỗi Database (constrains)
```
Không thể dành riêng X cái của "Sản phẩm Z" tại vị trí "Kho ABC".
Chỉ còn Y cái khả dụng.
```

## Troubleshooting

### Module không hoạt động
- ✅ Module đã install? Vào Apps và tìm "Công cụ Giới hạn"
- ✅ Odoo đã restart? Restart server Odoo
- ✅ Vị trí là internal? Kiểm tra cấu hình vị trí

### Số lượng không bị giới hạn
- ✅ Move có thể ở trạng thái done/cancel (bỏ qua kiểm tra)
- ✅ Vị trí có thể không phải internal (supplier, customer)
- ✅ Sản phẩm không xác định

### Popup không xuất hiện
- ✅ Chỉ hoạt động khi sửa qua UI
- ✅ Qua backend/API sẽ dùng constraint (báo lỗi)

### Vẫn nhảy thành 2 dòng
- ✅ Kiểm tra có bao nhiêu dòng trong move này
- ✅ Module chỉ kiểm soát dòng hiện tại, không chặn việc thêm dòng mới
- ✅ Nếu muốn chặn việc thêm dòng, cần thêm logic vào button thêm dòng

## Khác biệt Chính so với Code Gốc

### Code Gốc
```python
# Kiểm tra tồn kho toàn hệ thống
real_on_hand = quant.quantity if quant else 0.0
if self.quantity > real_on_hand:
    self.quantity = real_on_hand
```

### Module Cải tiến
```python
# Kiểm tra tồn kho trừ đi số đã dành riêng trong move
total_stock = self._get_total_stock_at_location()
reserved_qty = self._get_reserved_qty_in_move()
available_qty = total_stock - reserved_qty
if self.quantity > available_qty:
    self.quantity = available_qty
```

**Sự khác biệt:** Code gốc chỉ so sánh với tồn kho, nhưng không tính số lượng đã dành riêng khác trong cùng move, dẫn đến nhảy nhiều dòng.

## Hỗ trợ
Liên hệ HLV Team hoặc refer tài liệu Odoo về stock.move.line
