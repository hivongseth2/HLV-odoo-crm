# TECHNICAL DOCUMENTATION: export_outgoing_picking_excel

## 1. Mục đích module
Module này cung cấp các tính năng xuất báo cáo dưới dạng Excel (dùng thư viện `openpyxl`). Các báo cáo chủ yếu xoay quanh hoạt động xuất kho (outgoing pickings), nhập kho (purchase orders), tồn kho (inventory), báo cáo bán hàng, và các định dạng báo cáo đặc thù cho MISA hoặc Shopee.

## 2. Cấu trúc thư mục

```
export_outgoing_picking_excel/
├── models/
│   ├── __init__.py
│   ├── export_outgoing_picking_wizard.py   # Xuất lệnh xuất kho & mẫu POS CRM (Kế toán)
│   ├── export_purchase_order_wizard.py     # Xuất đơn mua hàng
│   ├── export_sales_report_wizard.py       # Báo cáo bán hàng (Được tinh gọn từ Xuất lệnh xuất kho)
│   ├── inventory_report_wizard.py          # Báo cáo tồn kho
│   ├── out_return_report_wizard.py         # Báo cáo hàng bán trả lại
│   ├── picking_export_shopee_wizard.py     # Xuất phiếu xuất kho định dạng Shopee
│   └── stock_export_wizard.py              # Báo cáo xuất nhập tồn kho
├── security/
│   └── ir.model.access.csv                 # Phân quyền cho wizards
├── views/
│   ├── inventory_report_wizard_views.xml
│   ├── out_return_report_wizard_views.xml
│   ├── picking_export_shopee_wizard_views.xml
│   ├── picking_export_wizard_views.xml     # Views cho export_outgoing_picking_wizard
│   ├── purchase_export_wizard_views.xml
│   ├── sales_report_export_wizard_views.xml# View cho export_sales_report_wizard
│   ├── stock_export_wizard_views.xml
│   └── stock_picking_views.xml             # Định nghĩa actions & Menu Items
├── __init__.py
└── __manifest__.py
```

## 3. Quy tắc kiến trúc & Nguyên tắc (DRY)
- **Kiến trúc TransientModel (Wizards)**: Mọi báo cáo đều được khởi tạo thông qua `models.TransientModel`. Mỗi loại báo cáo nằm ở một model riêng để tránh phình to code.
- **Thư viện xuất Excel**: Module sử dụng trực tiếp `openpyxl` thông qua BytesIO đễ tạo workbook, định dạng ô (cell alignment, borders, number formats) và trả về đối tượng `ir.attachment` URL để tải file về.
- **Sống sót khi không có `openpyxl`**: Các class được bọc trong vòng `try/except ImportError` nhằm ngăn Odoo crash lúc khởi động, và raise UserError nến gọi export mà thiếu lib.
- **Không ghi đè models gốc**: Logic chỉ thực hiện `search/browse` trên các object `stock.picking`, `sale.order`, `pos.order`, `stock.move` mà không cấy logic trực tiếp vào hệ thống gốc.

## 4. Các file / layers quan trọng (Wizards)

### 4.1. `export_outgoing_picking_wizard.py`
- **Model**: `picking.export.wizard`
- **Nhiệm vụ chính**: Xuất phiếu xuất kho theo format Kế Toán (chứa nhiều cột hardcode), và format dành riêng cho POS/CRM.
- **Tính năng đặc biệt**: 
  - Khả năng lần ngược từ phiếu xuất (`OUT`/`PACK`) về phiếu gốc (`PICK`) để lấy dữ liệu `pos.order.lines` (dùng cho quy trình xuất kho 3 bước).
  - Có cơ chế tách combo BoM Kit -> xuất dòng cha trước rồi duyệt move lấy dòng con.

### 4.2. `export_sales_report_wizard.py`
- **Model**: `picking.export.sales.report.wizard`
- **Nhiệm vụ chính**: Phiên bản thu gọn của (4.1) phục vụ cho cấp quản lý "Báo cáo bán hàng".
- **Sự khác biệt so với 4.1**:
  - Không bóc tách combo thành nhiều dòng (vì nó quá chi tiết). Nó tự gom nhóm (`group_by`) dựa trên `sale_line_id` và chỉ lấy ra 1 dòng duy nhất đại diện cho sản phẩm combo cha.
  - Loại bỏ các cột thông tin không hữu ích cho giám sát bán hàng (`Ngày hạch toán`, `Ngày chứng từ`, `Thuộc combo`, v.v.).

### 4.3. `picking_export_shopee_wizard.py`
- **Nhiệm vụ chính**: Trích xuất `sale_order` gắn kèm picking, bóc tách và tạo file Excel khớp định dạng order của Shopee (các mã đơn vị vận chuyển, trạng thái tracking đơn vị vận chuyển).

## 5. Luồng xử lý chung để xuất báo cáo
1. Người dùng mở Form Wizard (qua Actions trên thanh Menu Inventory/Reporting).
2. Điền điều kiện lọc (`date_from`, `date_to`, `warehouse_ids`...).
3. Click "Xuất Excel". Trình duyệt gọi hàm `action_export()` (hoặc hàm tương tự).
4. `action_export()` thực hiện:
   - Truy vấn (Search) các bản ghi thích hợp (VD: `stock.picking` có `state='done'`).
   - Khởi tạo mảng `data_rows`.
   - Vòng lặp lấy data từ Model -> đưa vào dictionary chứa thông tin cụ thể (thường nằm ở hàm `_build_row_data()`).
   - Gọi hàm `_create_excel_workbook(data_rows)`: 
      - Tạo Workbook, Worksheet.
      - Tạo loop vẽ Header (cùng font bôi đậm, màu nền, border).
      - Tạo loop fill giá trị vào từng Cell dựa trên mảng dictionary của `data_rows`.
   - Lưu trữ Workbook vào BytesIO.
   - Trả về hành động URL action chuyển hướng cho trình duyệt tự tải file attachment về.

## 6. Hướng dẫn mở rộng
- **Bổ sung cột vào báo cáo hiện tại**: 
  1. Tìm hàm `_get_columns_definition()` của wizard tương ứng và thêm dict `'key'`, `'name'`, `'width'`.
  2. Bổ sung việc map dữ liệu từ Model vào Dictionary ở hàm `_build_row_data()`. Cần đảm bảo `'key'` ở (1) với Dictionary (2) là đồng bộ.
- **Tạo một loại báo cáo xuất Excel hoàn toàn mới**:
  1. Thêm một file `.py` mới vào models (ví dụ `export_xyz_wizard.py`) và định nghĩa một Model kế thừa từ `TransientModel`.
  2. Copy template code tạo workbook openpyxl từ file `export_outgoing_picking_wizard.py` (như `_create_excel_workbook`).
  3. Thêm file xml khai báo view Form.
  4. Đăng ký menu vào `views/stock_picking_views.xml`.
  5. Sửa `__init__.py` và `__manifest__.py` để load file python/xml mới.
- **Refactoring Cảnh báo**: Nhiều code tạo Header/Excel Layout đang bị copy lại qua nhiều wizards. Để refactoring tốt hơn trong tương lai, nên có 1 file Helpers / Utility hoặc model Abstract để xử lý logic Openpyxl chung này.
