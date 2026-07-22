# Technical Documentation: hlv_purchase_line_custom

## 1. Tổng quan Module (Overview)
Module `hlv_purchase_line_custom` mở rộng model `purchase.order.line`, `stock.move`, và `stock.move.line` nhằm hỗ trợ bổ sung các thông tin chi tiết trên từng dòng Đơn mua hàng (Purchase Order) và **tự động liên kết liên thông (link) sang Phiếu nhập kho (Stock Picking)**:
- **Cột MISA org_ref_detail_id**: Trường `related` từ `purchase_line_id.misa_purchase_order_org_ref_detail_id` hiển thị mã định danh duy nhất của dòng Đơn mua hàng trên Phiếu nhập kho (`stock.move` và `stock.move.line`).
- **Cột Năm sản xuất (`production_year`)**: Trường nhập liệu văn bản (`Char`) từ PO line tự động kế thừa và liên kết sang Dịch chuyển kho (`stock.move`) và Chi tiết dịch chuyển kho (`stock.move.line`).
- **Cột Xuất xứ (`country_of_origin`)**: Trường nhập liệu văn bản (`Char`) từ PO line tự động kế thừa và liên kết sang Dịch chuyển kho (`stock.move`) và Chi tiết dịch chuyển kho (`stock.move.line`).

## 2. Cấu trúc Thư mục (Directory Structure)
```
hlv_purchase_line_custom/
├── __init__.py
├── __manifest__.py
├── TECHNICAL.md
├── models/
│   ├── __init__.py
│   ├── purchase_order_line.py
│   ├── stock_move.py
│   └── stock_move_line.py
└── views/
    ├── purchase_order_views.xml
    └── stock_picking_views.xml
```

## 3. Chi tiết Kỹ thuật (Technical Specifications)

### 3.1 Model `purchase.order.line`
- File: `models/purchase_order_line.py`
- Kế thừa: `purchase.order.line`
- Fields bổ sung:
  - `stt` (`fields.Char`): Compute non-stored field. Tính toán tự động theo chuỗi các dòng thuộc `order_id`.
  - `production_year` (`fields.Char`): Năm sản xuất của sản phẩm.
  - `country_of_origin` (`fields.Char`): Xuất xứ của sản phẩm.
- Method overrides:
  - `_prepare_stock_moves(picking)`: Gửi giá trị `production_year` và `country_of_origin` sang `stock.move` khi xác nhận đơn mua hàng.

### 3.2 Model `stock.move`
- File: `models/stock_move.py`
- Kế thừa: `stock.move`
- Fields bổ sung:
  - `misa_purchase_order_org_ref_detail_id` (`fields.Char`): Related tới `purchase_line_id.misa_purchase_order_org_ref_detail_id`, `store=True`, `readonly=True`.
  - `production_year` (`fields.Char`): Related tới `purchase_line_id.production_year`, `store=True`, `readonly=False`.
  - `country_of_origin` (`fields.Char`): Related tới `purchase_line_id.country_of_origin`, `store=True`, `readonly=False`.

### 3.3 Model `stock.move.line`
- File: `models/stock_move_line.py`
- Kế thừa: `stock.move.line`
- Fields bổ sung:
  - `misa_purchase_order_org_ref_detail_id` (`fields.Char`): Related tới `move_id.misa_purchase_order_org_ref_detail_id`.
  - `production_year` (`fields.Char`): Related tới `move_id.production_year`.
  - `country_of_origin` (`fields.Char`): Related tới `move_id.country_of_origin`.

### 3.4 View Extensions
- File: `views/purchase_order_views.xml`: Kế thừa `purchase.order` form và `purchase.order.line` list view để hiển thị STT, Năm sản xuất, Xuất xứ trên Đơn mua hàng.
- File: `views/stock_picking_views.xml`: Kế thừa `stock.picking` form view và `stock.move.line` detailed operations tree view để hiển thị `MISA org_ref_detail_id`, Năm sản xuất, Xuất xứ trên Phiếu nhập kho (ẩn hiển thị STT thừa).

## 4. Hướng dẫn Nâng cấp & Mở rộng (Extension Guide)
- Khi xác nhận đơn mua hàng (PO), Odoo tự động gọi `_prepare_stock_moves` và gán `purchase_line_id` cho `stock.move`. Thông tin `MISA org_ref_detail_id`, Năm sản xuất, Xuất xứ sẽ hiển thị đồng nhất từ PO sang Phiếu nhập kho.
