# Module Công cụ Giới hạn Số lượng Dòng Chuyển kho

## Tổng quan
Module này cung cấp **2 công cụ chính** cho quản lý stock:

### 1. Kiểm soát Số lượng
Ngăn chặn user nhập số lượng giữ tồn vượt quá tồn kho thực tế. Giải quyết vấn đề:
- Nhảy thành nhiều dòng khi nhập số lượng cao
- User nhập quá tồn kho có sẵn
- Tự động điều chỉnh về mức khả dụng

### 2. Debug Tool
Phân tích chi tiết tại sao picking không assign được. Chẩn đoán:
- **Hàng phân tán**: Stock ở nhiều vị trí → Cần gộp lại
- **Thiếu hàng**: Không đủ toàn phần → Cần nhập thêm
- **Quant issues**: Lock, UoM mismatch, etc

## Tính Năng
✅ **Kiểm tra Real-time**: Thông báo khi user thay đổi quantity  
✅ **Tự động điều chỉnh**: Giới hạn số lượng đến mức khả dụng  
✅ **Ràng buộc Database**: Ngăn lưu dữ liệu không hợp lệ qua API  
✅ **Chỉ áp dụng Kho Nội bộ**: Bỏ qua warehouse, supplier, customer locations  
✅ **Debug Picking**: 🆕 Công cụ phân tích picking assign chi tiết  
✅ **Multi-location Detection**: 🆕 Chỉ ra hàng phân tán ở nhiều nơi

## Cách Cài đặt

1. **Module đã tạo tại:**  
   `custom_addons/stock_move_line_quantity_limit/`

2. **Cập nhật Apps List:**
   - Settings > Apps > Update Apps List

3. **Cài đặt Module:**
   - Tìm "Công cụ Giới hạn Số lượng Dòng Chuyển kho"
   - Nhấn **Install**

4. **Restart Odoo** (nếu cần)

## Sử Dụng

### Kiểm soát Quantity (Tự động)
Khi user sửa quantity trong stock.move.line:
1. Nếu nhập > available → Popup cảnh báo
2. Tự động điều chỉnh về mức có sẵn
3. Nếu vẫn save là invalid → Database constraint block

### Debug Picking (Manual)
Khi picking không assign được:

1. Vào **Inventory > Debug Picking**
2. Chọn picking order gặp lỗi
3. Nhấn **🔍 Phân tích Lỗi**
4. Xem output:

```
✅ SẢN PHẨM CÓ Ở CÁC VỊ TRÍ:
  • KBC/Tồn kho/A1-T1/Thung-1: Qty=2, Available=2
  • KBC/Tồn kho/A1-T1/Thung-2: Qty=2, Available=2
  
📊 TỔNG AVAILABLE TẠI TẤT CẢ LOCATIONS: 4
✅ ĐỦ HÀNG (nhưng có thể phân tán)

⚠️ HÀNG PHÂN TÁN - Cần combine multiple locations!
```

**Hành động:**
- Nếu "HÀNG PHÂN TÁN" → Tạo transfer gộp hàng vào 1 location
- Nếu "THIẾU HÀNG" → Nhập thêm hoặc giảm qty picking

## Lợi ích

| Vấn đề | Giải pháp |
|-------|----------|
| Nhập quá qty | ✅ Real-time warning + auto-adjust |
| Assign fail | ✅ Debug tool chỉ ra nguyên nhân |
| Hàng phân tán | ✅ 💡 Đề xuất gộp multiple locations |
| Thiếu hàng | ✅ 💡 Đề xuất nhập thêm |

## Ví dụ Thực Tế

**Tình huống:** Hàng có 4 cái ở 2 vị trí, đơn cần 3 cái

**Trước module:**
```
❌ Không assign được!
❌ User không biết lý do → Phải vào move line chọn tay
```

**Sau module:**
```
1️⃣ Debug tool báo: "Hàng phân tán ở 2 locations, total 4 cái OK"
2️⃣ User tạo transfer gộp 2 location về 1
3️⃣ Assign thành công!
```

## Troubleshooting

### Module không xuất hiện
- ✅ Update Apps List lại
- ✅ Restart Odoo
- ✅ Clear cache browser

### Debug tool không chính xác
- ✅ Check stock.quant records
- ✅ Check location types (phải internal)

### Vẫn assign không được
- ✅ Có thể stock bị lock
- ✅ Check hlv_priority_stock_reservation module
- ✅ Hoặc UoM (Unit of Measure) mismatch

## Phục Thuộc

- `stock` (Odoo base module)
- Kompatibel với tất cả inventory modules

## Version History

- **v18.0.1.0.0** (2026-03): Initial release + Debug tool
  - Kiểm soát quantity
  - Debug picking assign
  - Multi-location detection

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
