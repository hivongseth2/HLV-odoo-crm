# 📋 CONSOLIDATION: Xóa stock_move_force_assign

## Lý do
Module `stock_move_force_assign` đã bị **gộp** vào `stock_move_line_quantity_limit`

## Thay đổi
| Item | Trước | Sau |
|------|-------|-----|
| **stock_move_force_assign** | Riêng module | ❌ ĐƯỢC XÓA |
| **Debug Tool** | Ở stock_move_force_assign | ✅ Moved to quantity_limit |
| **Quantity Validation** | Ở quantity_limit | ✅ Giữ nguyên |
| **Module chủ** | Cách rời | ✅ quantity_limit duy nhất |

## Cách Xóa (Manual)

### Option 1: Xóa folder hoàn toàn
```bash
rm -rf custom_addons/stock_move_force_assign/
```

### Option 2: Uninstall + Disable
1. Vào Apps
2. Tìm "Stock Move Force Assign"
3. Click ⋯ > Uninstall
4. (Optional) Delete folder sau

## Cập nhật Modules Cần Thiết

Chỉ cần:
1. **Reinstall**: "Công cụ Giới hạn Số lượng Dòng Chuyển kho"
2. Hoặc **Update** nếu đã cài

## Tính Năng Sau Consolidation

**stock_move_line_quantity_limit** (unified module):
```
✅ Kiểm soát Quantity (từ cũ)
✅ Debug Picking Tool (từ force_assign)
✅ Multi-location Detection (NEW)
✅ Recommendation Engine (NEW)
```

không còn cần `stock_move_force_assign`!

## Benefit
- ✅ Ít modules, dễ maintain
- ✅ Không conflict
- ✅ Centralized quantity + assign logic
- ✅ Clear responsibility

---
**Date:** 2026-03-12
**Status:** Ready to delete
