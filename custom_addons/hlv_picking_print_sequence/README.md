# HLV Stock Picking Print Sequence

## Mô tả Module

Module sắp xếp thứ tự in biên bản đi (Delivery Order) cho Odoo 18. Cho phép người dùng tùy chỉnh thứ tự in của các phiếu kho một cách linh hoạt.

## Tính Năng Chính

✅ **Trường Thứ tự in** - Thêm trường `print_sequence` cho mỗi phiếu kho
✅ **Sắp xếp thủ công** - Nhập trực tiếp số thứ tự hoặc kéo thả để sắp xếp  
✅ **Tự động đánh số** - Tự động đánh số theo ngày tạo (cũ trước, mới sau)
✅ **In theo thứ tự** - In biên bản đi theo thứ tự đã sắp xếp
✅ **Lọc nhanh** - Filter "Có thứ tự in" và "Chưa sắp xếp"  
✅ **Ghi chú** - Thêm ghi chú về lý do sắp xếp
✅ **Hỗ trợ nhiều loại phiếu** - Xuất kho, nhập kho, chuyển nội bộ

## Hướng Dẫn Sử Dụng

### 1. Cài đặt Module

```bash
# Vào Settings > Apps > Update Apps List
# Tìm "HLV Stock Picking Print Sequence"
# Click Install
```

### 2. Quy trình Sắp xếp Thứ tự

**Cách 1: Sắp xếp thủ công**
1. Vào `Inventory > Sắp xếp thứ tự in > Xuất kho`
2. Nhập số thứ tự trong cột "Thứ tự in" (số nhỏ in trước)
3. Nếu cần, thêm ghi chú trong cột "Ghi chú sắp xếp"
4. Click "Save"

**Cách 2: Sắp xếp tự động**
1. Chọn nhiều phiếu kho
2. Click vào "⋮" (menu)
3. Chọn "Đánh số thứ tự tự động"
4. Hệ thống sẽ tự động đánh số dựa trên ngày tạo

**Cách 3: In theo thứ tự**
1. Từ view danh sách, chọn các phiếu cần in
2. Click nút "In theo thứ tự"
3. Hệ thống sẽ in theo số thứ tự (nhỏ trước)

### 3. Các Bộ lọc Hữu ích

- **Có thứ tự in** - Chỉ hiển thị những phiếu đã gán sequence
- **Chưa sắp xếp** - Chỉ hiển thị những phiếu chưa có thứ tự (sequence = 0)

## Chi tiết Fields

| Field | Loại | Mô tả |
|-------|------|-------|
| `print_sequence` | Integer | Số thứ tự in (0 = chưa sắp xếp, 1, 2, 3... = thứ tự) |
| `print_sequence_note` | Text | Ghi chú lý do sắp xếp |

## Examples Python API

```python
# Lấy danh sách phiếu theo thứ tự
picking = env['stock.picking']
sorted_pickings = picking.search([
    ('print_sequence', '>', 0),
    ('state', '=', 'done')
], order='print_sequence asc')

# Tự động đánh số
pickings = picking.search([('state', 'in', ['waiting', 'confirmed'])])
pickings._assign_print_sequence_by_date(start_seq=1)

# Lấy phiếu theo ngày và loại
done_pickings = picking.get_sorted_pickings_for_print(
    picking_type_code='outgoing',
    date_from='2024-01-01',
    date_to='2024-01-31'
)

# In theo thứ tự
pickings.action_print_by_sequence()
```

## Menu Items

Module thêm các menu items:

- **Inventory > Sắp xếp thứ tự in** - Menu chính
  - **Xuất kho** - Sắp xếp phiếu xuất kho
  - **Chuyển nội bộ** - Sắp xếp phiếu chuyển nội bộ

## Quy tắc Ưu tiên In

Khi chọn "In theo thứ tự":
1. Phiếu có `print_sequence` lớn hơn 0 được in trước (theo số nhỏ trước)
2. Phiếu không có `print_sequence` (= 0) sẽ bị bỏ qua hoặc in cuối

Ví dụ:
```
Print sequence = 1 → In trước
Print sequence = 2 → In thứ hai
Print sequence = 5 → In thứ ba
Print sequence = 0 → Bị bỏ qua
```

## Tính năng Advanced

### Auto-assign sequence

Sử dụng server action để tự động gán sequence cho những phiếu chưa có:

```python
# Code trong server action
records_to_sequence = records.filtered(lambda p: p.print_sequence == 0)
if records_to_sequence:
    sorted_rec = records_to_sequence.sorted(key=lambda p: p.create_date)
    for idx, picking in enumerate(sorted_rec, 1):
        picking.print_sequence = idx
```

### Reset sequence

Xóa tất cả sequence (cho phép sắp xếp lại):

```python
# Code trong server action
records.write({
    'print_sequence': 0,
    'print_sequence_note': ''
})
```

## Troubleshooting

**Q: Nó không hiển thị cột "Thứ tự in" trong danh sách?**
A: Cột này được ẩn mặc định. Click vào "▼" (dropdown columns) và chọn "Thứ tự in"

**Q: Tôi muốn in tất cả phiếu cùng một lúc?**
A: Sử dụng "In theo thứ tự" sau khi đã gán sequence cho các phiếu

**Q: Có thể xóa sequence để sắp xếp lại?**
A: Có, click menu "⋮" และ chọn "Xóa thứ tự in"

## Phiên bản

- **v1.0.0** (2024) - Phiên bản đầu tiên với các tính năng cơ bản

## Dependencies

- `stock` - Module quản lý kho của Odoo
- `web` - Module web của Odoo

## License

© HoanglongVU - All rights reserved

## Support

Để báo cáo lỗi hoặc đề xuất tính năng, liên hệ đội phát triển.
