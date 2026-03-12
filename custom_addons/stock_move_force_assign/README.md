# Stock Move Force Assign Module

## Vấn đề Sửa chữa

**Tình trạng:** Picking không assign được dù hàng có trong kho
- Bấm "Kiểm tra tình trạng còn hàng" không hoạt động
- Phải vào move line chọn tay
- Lỗi này thỉnh thoảng xảy ra

**Nguyên nhân:** Odoo's `_action_assign()` không thể tìm quant phù hợp hoặc có vấn đề logic

## Giải pháp

### 1. Cải tiến `action_assign()` - StockPicking
- Thêm logging chi tiết
- Khi assign fail, fallback sang assign từng move
- Ghi log lỗi để debug

### 2. Cải tiến `_action_assign()` - StockMove
- Nếu assign bình thường fail, tự động tạo move line
- Dùng hàm `_get_available_qty()` để tính chính xác
- Fallback sang `partially_available` nếu cần

### 3. Auto-create Move Line
- Khi move không có move line, tự động tạo
- Dùng khi assign normal không hoạt động
- Tính qty available từ quant trực tiếp

## Tính Năng

✅ **Logging chi tiết** - Ghi log mọi bước assign
✅ **Fallback logic** - Thử nhiều cách nếu cách 1 fail
✅ **Auto move line** - Tạo move line khi cần
✅ **Partial assign** - Nếu không đủ hàng, assign phần có

## Cách Cài đặt

1. Copy module vào `custom_addons/stock_move_force_assign/`
2. Vào Settings > Apps > Update Apps List
3. Cài đặt "Stock Move Force Assign"
4. Restart Odoo

## Cách Debug

### 1. Kiểm tra Log
```
Vào menu Developer > Logs
Tìm picking order đó
Xem logs "Picking XXX - action_assign..."
```

### 2. Chạy Script Debug
```
python debug_stock_assign.py (trong Odoo shell)
```

## Nếu Vẫn Không Fix

Có thể là:
1. **Virtual location (ID=15) sai** - Kiểm tra trong production_operation.py
2. **Stock quant bị locked** - Kiểm tra kho setting
3. **UoM mismatch** - Kiểm tra Unit of Measure
4. **Concurrent issue** - Có nhiều picking cùng lúc

Hãy check log kỹ để tìm nguyên nhân!
