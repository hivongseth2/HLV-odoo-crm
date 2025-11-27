# Stock Quantity Validation

## Mô tả

Module này ngăn chặn việc xác nhận phiếu kho (picking) khi số lượng thực tế (qty_done) lớn hơn số lượng đã đặt (product_uom_qty) trên stock.move.

## Tính năng

- ✅ Kiểm tra tất cả move lines trong picking trước khi xác nhận
- ✅ Hiển thị thông báo lỗi chi tiết với danh sách sản phẩm vi phạm
- ✅ Áp dụng cho tất cả loại picking (Pick, Pack, Delivery/Out, Receipt, etc.)
- ✅ Log cảnh báo chi tiết để dễ dàng debug
- ✅ Xử lý chính xác với floating point (epsilon tolerance)

## Cài đặt

1. Copy module vào thư mục `custom_addons`
2. Update Apps list trong Odoo
3. Tìm và cài đặt module "Stock Quantity Validation"

## Cách sử dụng

Module tự động hoạt động sau khi cài đặt. Không cần cấu hình thêm.

### Khi nào module chặn xác nhận?

Module sẽ chặn và hiển thị lỗi khi:
- User click nút "Validate" trên picking
- Có ít nhất một stock.move có `quantity_done` > `product_uom_qty`

### Thông báo lỗi

Khi vi phạm, user sẽ thấy thông báo:

```
Không thể xác nhận phiếu WH/OUT/00123!

Số lượng thực tế (Done) không được vượt quá số lượng đã đặt (Demand):

• Sản phẩm A: Đã làm 150.00 Cái (vượt quá 100.00 Cái đã đặt)
• Sản phẩm B: Đã làm 75.50 Kg (vượt quá 50.00 Kg đã đặt)

Vui lòng điều chỉnh số lượng trước khi xác nhận.
```

## Kỹ thuật

### File cấu trúc

```
stock_quantity_validation/
├── __init__.py
├── __manifest__.py
├── README.md
└── models/
    ├── __init__.py
    └── stock_picking.py
```

### Override methods

1. **StockPicking.button_validate()**: Kiểm tra validation trước khi gọi super()
2. **StockMove._compute_quantity_done()**: Log warning khi phát hiện qty_done > product_uom_qty

### Dependencies

- `stock` (Odoo Inventory module)

## Tác giả

HLV Team

## License

LGPL-3
