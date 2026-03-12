# 🔧 FIX STOCK ASSIGN ISSUE - Hướng dẫn

## ⚠️ Vấn đề Vừa Gặp

```
StockMove._action_assign() got an unexpected keyword argument 'force_qty'
```

**Nguyên nhân:** Module `stock_move_force_assign` (vừa tạo) conflict với module `hlv_priority_stock_reservation` hiện có

## ✅ Giải Pháp Đã Thực Hiện

### 1. Sửa Lỗi Odoo 18
- ✅ `move_lines` → `move_ids`   (Odoo 18 field name)
- ✅ `_action_assign()` signature → `*args, **kwargs`

### 2. Disable Conflicting Overrides
```
Module: stock_move_force_assign
❌ Bỏ: def action_assign() override
❌ Bỏ: def _action_assign() override
✅ Giữ: Debug tool (TransientModel)
✅ Giữ: Helper functions
```

## 📋 Cách Forward

### Step 1: Restart Odoo
```
Ctrl+C trong terminal Odoo
python manage.py runserver  (hoặc lệnh tương ứng)
```

### Step 2: Update Module
```
Apps > Update Apps List
Tìm: "Stock Move Force Assign"
Click: ⟳ (Update / Reinstall)
```

### Step 3: Test Picking Assignment
```
Vào: Sales > Orders > Chọn 1 order
Kiểm tra: "Kiểm tra tình trạng còn hàng"
Kết quả: 
  ✅ Assign thành công
  ❌ Vẫn fail → Dùng Debug Tool
```

### Step 4: Nếu Vẫn Fail - Dùng Debug Tool
```
Vào: Inventory > Debug Picking
Chọn: Picking order bị lỗi
Nhấn: 🔍 Kiểm tra Lỗi
Xem: Output chi tiết
```

## 🔍 Debug Output Giải Thích

### ✅ QUANT TỒN TẠI
```
QUANT TỒN TẠI
  • Quantity: 5
  • Reserved: 2
  • Available: 3
```
→ **OK**, hàng có sẵn, assign phải work

### ❌ KHÔNG CÓ QUANT TẠI ĐỊA ĐIỂM NÀY
```
KHÔNG CÓ QUANT TẠI ĐỊA ĐIỂM NÀY!
💡 Sản phẩm này ở những nơi khác:
   • KBC/Tồn kho/A-T2: 3 (available: 3)
```
→ **Vấn đề**: Hàng ở location khác!  
Cần check:
- Location_id của move có đúng không?
- Stock quant location config có sai không?

### ⚠️ KHÔNG ĐỦ HÀNG
```
⚠️  Move XYZ: Không đủ hàng (1 < 3)
```
→ **Vấn đề**: Thiếu số lượng  
Cần:
- Nhập thêm hàng vào kho
- Hoặc giảm số lượng picking

## 💡 Nếu Vẫn Không Fix

| Triệu chứng | Khả năng nguyên nhân | Cách khắc phục |
|-----------|-----------------|----------|
| Có quant nhưng không assign | Stock bị lock | Check kho setting / Clear lock |
| Quant ở location khác | Move location sai | Kiểm tra sales order location |
| UoM mismatch | Unit không khớp | Check product UoM |
| Repeat lỗi | Concurrent issue | Thử assign lần 2 hoặc 3 |

## 📞 Tiếp Theo

Nếu issue vẫn persist:
1. Run `debug_stock_assign.py` (script cho Odoo shell)
2. Check `hlv_priority_stock_reservation` config
3. Có thể cần fix `production_operation.py` virtual location

---

**Tạo:** 2026-03-12
**Module:** stock_move_force_assign v18.0.1.0.0
**Status:** ✅ Fixed (conflict removed)
