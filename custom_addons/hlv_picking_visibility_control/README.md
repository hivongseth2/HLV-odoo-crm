# Module: Kiểm soát hiển thị Phiếu bàn giao (HLV Picking Visibility Control)

## Mô tả
Module này cho phép ẩn các loại phiếu bàn giao (BBGN, BBBG, phiếu nội bộ, v.v.) khỏi menu chính. 
Các phiếu này sẽ chỉ có thể được xem và in thông qua phiếu xuất kho chính.

## Tính năng chính

### 1. Ẩn Loại Phiếu
- Thêm trường "Ẩn từ Menu chính" cho `stock.picking.type`
- Khi check, tất cả phiếu của loại này sẽ bị ẩn khỏi danh sách chính
- Chỉ nhân viên quản lý mới có thể xem tất cả phiếu

### 2. Kiểm soát hiển thị Phiếu
- Trường `is_hidden_picking`: Tự động tính toán xem phiếu có nên bị ẩn
- Trường `allow_menu_access`: Cho phép manual override để phiếu có thể xem từ menu

### 3. In Phiếu Bàn Giao
- Button "In Phiếu Bàn Giao" từ phiếu xuất kho
- Tự động tìm và in các phiếu bàn giao liên quan

### 4. Search & Filter
- Filter "Hiển thị Phiếu ẩn": Xem các phiếu bị ẩn
- Filter "Chỉ Phiếu ẩn": Xem chỉ phiếu ẩn
- Filter trên Loại phiếu: Xem loại phiếu bị ẩn

## Cách sử dụng

### Bước 1: Cấu hình Loại Phiếu
1. Đi tới: **Inventory > Configuration > Picking Types**
2. Mở loại phiếu bàn giao (ví dụ: BBGN, BBBG)
3. Tìm section "Kiểm soát Hiển thị"
4. Check các trường:
   - **Ẩn từ Menu chính**: Ẩn phiếu khỏi danh sách chính
   - **Là loại phiếu bàn giao**: Đánh dấu đây là loại phiếu bàn giao
5. Lưu

### Bước 2: Xem Phiếu
- **Người dùng bình thường**: 
  - Chỉ thấy phiếu xuất kho chính
  - Các phiếu bàn giao bị ẩn tự động
  
- **Quản lý Kho**:
  - Có thể xem tất cả phiếu
  - Có hành động "Tất cả Phiếu" trong menu

### Bước 3: In Phiếu Bàn Giao
1. Mở phiếu xuất kho chính
2. Nhấn button "In Phiếu Bàn Giao"
3. Module sẽ tự động tìm và in phiếu bàn giao liên quan

## Cấu trúc dữ liệu

### Mở rộng `stock.picking.type`
```python
- is_hidden_from_menu: Boolean (default=False)
- is_delivery_note_type: Boolean (default=False)
```

### Mở rộng `stock.picking`
```python
- is_hidden_picking: Boolean (computed, store=True)
- allow_menu_access: Boolean (default=False)
```

## Domain lọc
Phiếu sẽ bị ẩn nếu:
- `picking_type_id.is_hidden_from_menu = True` AND
- `allow_menu_access = False`

## Views được thêm/sửa
1. `stock.picking.form` - Thêm thông báo và button
2. `stock.picking.tree` - Hiển thị phiếu ẩn với màu muted
3. `stock.picking.search` - Thêm filters
4. `stock.picking.type.form` - Thêm section kiểm soát
5. `stock.picking.type.tree` - Hiển thị status

## Các action được tạo
- `action_picking_main_list`: Phiếu xuất kho chính (ẩn phiếu)
- `action_picking_all_list`: Tất cả phiếu (cho quản lý)

## Ví dụ cấu hình

### Loại phiếu BBGN (Bản giao nhận)
```
Tên: BBGN
Sequence: BBGN/
Ẩn từ Menu chính: ✓
Là loại phiếu bàn giao: ✓
```

### Loại phiếu BBBG (Bản bàn giao)
```
Tên: BBBG
Sequence: BBBG/
Ẩn từ Menu chính: ✓
Là loại phiếu bàn giao: ✓
```

### Loại phiếu OUT (Xuất kho)
```
Tên: Phiếu Xuất kho
Sequence: OUT/
Ẩn từ Menu chính: (không check)
Là loại phiếu bàn giao: (không check)
```

## Quyền hạn
- **Người dùng bình thường**: Chỉ đọc
- **Quản lý kho**: Đầy đủ quyền

## Ghi chú
- Module tự động filter phiếu ẩn trong `search()`
- Sử dụng `context.get('show_all_pickings')` để bypass filter
- Button in chỉ hiển thị trên phiếu OUT (outgoing picking)
- Phiếu ẩn được hiển thị với màu muted trong danh sách
