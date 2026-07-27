# Technical Documentation: hlv_purchase_line_custom

## 1. Tổng quan Module (Overview)
Module `hlv_purchase_line_custom` mở rộng model `purchase.order.line`, `stock.move`, và `stock.move.line` nhằm hỗ trợ bổ sung các thông tin chi tiết trên từng dòng Đơn mua hàng (Purchase Order) và **tự động liên kết liên thông (link) sang Phiếu nhập kho (Stock Picking)**:
- **Cột MISA org_ref_detail_id**: Trường `related` từ `purchase_line_id.misa_purchase_order_org_ref_detail_id` hiển thị mã định danh duy nhất của dòng Đơn mua hàng trên Phiếu nhập kho (`stock.move` và `stock.move.line`).
- **Cột Năm sản xuất (`production_year`)**: Trường nhập liệu văn bản (`Char`) từ PO line, liên kết sang `stock.move.line` qua chuỗi related `move_id.purchase_line_id.production_year`.
- **Cột Xuất xứ (`country_of_origin`)**: Trường nhập liệu văn bản (`Char`) từ PO line, liên kết sang `stock.move.line` qua chuỗi related `move_id.purchase_line_id.country_of_origin`.

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
  - `picking_ids` (`fields.Many2many`): Computed, các phiếu nhập kho liên kết.
  - `picking_count` (`fields.Integer`): Computed, số lượng phiếu nhập.
- **Lưu ý**: KHÔNG override `_prepare_stock_moves` vì `production_year` và `country_of_origin` không nằm trên `stock.move`. Các field này được lấy qua related chain trên `stock.move.line`.

### 3.2 Model `stock.move`
- File: `models/stock_move.py`
- Kế thừa: `stock.move`
- Fields bổ sung:
  - `stt` (`fields.Char`): Computed, số thứ tự của dòng.
  - `misa_purchase_order_org_ref_detail_id` (`fields.Char`): Related tới `purchase_line_id.misa_purchase_order_org_ref_detail_id`, `store=True`, `readonly=True`.
- **Lưu ý**: `production_year` và `country_of_origin` KHÔNG nằm trên model này. Chúng chỉ nằm trên `stock.move.line`.

### 3.3 Model `stock.move.line`
- File: `models/stock_move_line.py`
- Kế thừa: `stock.move.line`
- Fields bổ sung:
  - `stt` (`fields.Char`): Related tới `move_id.stt`.
  - `production_year` (`fields.Char`): Related tới `move_id.purchase_line_id.production_year`, `store=True`, `readonly=False`.
  - `country_of_origin` (`fields.Char`): Related tới `move_id.purchase_line_id.country_of_origin`, `store=True`, `readonly=False`.
  - `misa_purchase_order_org_ref_detail_id` (`fields.Char`): Related tới `move_id.misa_purchase_order_org_ref_detail_id`.

### 3.4 View Extensions
- File: `views/purchase_order_views.xml`:
  - Kế thừa `purchase.order` form view: Hiển thị STT, Năm sản xuất, Xuất xứ, Phiếu nhập kho trên bảng dòng sản phẩm.
  - Kế thừa `purchase.order.line` list view: Hiển thị STT, Năm sản xuất, Xuất xứ.
- File: `views/stock_picking_views.xml`:
  - Kế thừa `stock.view_picking_form`: Thêm cột MISA org_ref_detail_id vào `move_ids_without_package` (Operations tab).
  - Kế thừa `stock.view_stock_move_line_detailed_operation_tree`: Thêm MISA org_ref_detail_id, Năm sản xuất, Xuất xứ vào danh sách chi tiết (hiện khi bấm nút "Moves").
  - Kế thừa `stock.view_stock_move_line_operation_tree`: Thêm Năm sản xuất, Xuất xứ vào popup chi tiết move line (hiện khi mở chi tiết stock.move).

## 4. Hướng dẫn Nâng cấp & Mở rộng (Extension Guide)
- Khi xác nhận đơn mua hàng (PO), Odoo tự động gán `purchase_line_id` cho `stock.move`. Thông tin Năm sản xuất và Xuất xứ được truyền sang `stock.move.line` qua chuỗi related `move_id.purchase_line_id`.
- Nếu cần thêm field mới từ PO line sang picking, thêm related field vào `stock_move_line.py` (KHÔNG thêm vào `stock_move.py`), sau đó thêm vào view tương ứng.
