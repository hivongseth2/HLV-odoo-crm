# Stock Move Line Quantity Limit Module

## Overview
Module này ngăn chặn người dùng nhập số lượng giữ tồn (quantity) vượt quá số lượng tồn thực tế tại vị trí trong kho.

## Tính Năng
✅ **Kiểm tra Real-time**: Thông báo ngay khi user cố gắng nhập số lượng vượt quá tồn kho
✅ **Tự động điều chỉnh**: Tự động giới hạn số lượng đến mức khả dụng
✅ **Ràng buộc Database**: Ngăn cản việc lưu dữ liệu không hợp lệ qua API hoặc bulk operations
✅ **Thích hợp Kho Nội bộ**: Chỉ áp dụng cho kho nội bộ (internal locations)

## Cách Hoạt động

### 1. Khi User Thay đổi Số lượng (UI)
- Module kiểm tra số lượng tồn thực tế tại vị trí
- Nếu vượt quá, hiển thị popup cảnh báo
- Tự động điều chỉnh số lượng độiến mức có sẵn

### 2. Khi Lưu Record
- Ràng buộc `_check_quantity_not_exceed_stock` sẽ kiểm tra lại
- Nếu dữ liệu không hợp lệ, ngăn cản lưu và hiển thị lỗi

### 3. Tính toán Số lượng
- **`_get_available_quantity()`**: Lấy tồn kho thực tế tại vị trí
- **`_get_quantity_with_reserved()`**: Lấy số lượng đã dành riêng (reserved)

## Cách Cài đặt

1. **Copy module vào** `custom_addons/stock_move_line_quantity_limit/`
2. **Cập nhật Apps List** trong Odoo:
   - Vào Settings > Apps > Update Apps List
3. **Cài đặt Module**:
   - Tìm "Stock Move Line Quantity Limit"
   - Nhấn **Install**

## Thay đổi So với Code Ban đầu

| Tính Năng | Code Gốc | Module Cải tiến |
|-----------|----------|-----------------|
| Kiểm tra Real-time | ✅ @api.onchange | ✅ @api.onchange |
| Ràng buộc Database | ❌ Không | ✅ @api.constrains |
| Tính toán Tồn kho | Cơ bản | ✅ Tính reserved qty |
| Xử lý Edge cases | ❌ Không | ✅ Có |
| Thông báo | ✅ Warning | ✅ Warning |
| Tình trạng Moves | Cơ bản | ✅ Kiểm tra done/cancel |

## Các Tình huống Được Xử lý

### ✅ Được Áp dụng
- Nhập số lượng vào draft moves
- Chỉnh sửa số lượng trên stock.move.line
- API calls cố gắng sét số lượng không hợp lệ
- Bulk operations

### ❌ Không Áp dụng
- Moves ở trạng thái "done" (hoàn thành)
- Moves ở trạng thái "cancel" (hủy)
- Kho không phải loại "internal" (internal locations)
- Sản phẩm không xác định

## Ví dụ Sử dụng

### Trong Giao diện (UI)
```
1. Mở Stock Move
2. Chỉnh sửa số lượng > số lượng tồn kho thực tế
3. Hệ thống tự động:
   - Hiển thị popup cảnh báo
   - Điều chỉnh số lượng lại
```

### Qua API
```python
# Python ORM - Sẽ raise ValidationError nếu vượt quá
move_line = env['stock.move.line'].create({
    'product_id': 123,
    'quantity': 1000,  # Vượt quá tồn kho
    'location_id': 456,
})
# -> ValidationError: Cannot reserve 1000 units...
```

## Logging
Module sẽ ghi log các tính toán ngày:
```
[stock_move_line_quantity_limit] 
Checking quantity: 50 vs available: 30 at location: WH/Stock
```

## Troubleshooting

### Module không hoạt động
- ✅ Kiểm tra module đã được install chưa
- ✅ Kiểm tra Odoo đã restart chưa
- ✅ Kiểm tra vị trí là loại "internal" không

### Số lượng không bị giới hạn
- ✅ Moves có thể ở trạng thái done/cancel (không kiểm soát)
- ✅ Vị trí có thể không phải internal (e.g., supplier, customer)

### Popup không hiển thị
- ✅ Chỉ hoạt động khi sửa qua UI, không qua backend
- ✅ Hãy dùng constraint để bắt lỗi ở backend

## Hỗ trợ
Liên hệ HLV Team hoặc tham khảo Odoo Documentation về stock.move.line
