# deltatech_picking_transit — Technical

## 1. Mục đích
Chuyển hàng giữa hai kho theo 2 bước:

```
Bước 1 (INT kho nguồn):   KBC/Tồn kho      → KBC/CHUYENKHO
Bước 2 (phiếu kho nhận):  KBC/CHUYENKHO    → TSN/Stock   (tự sinh khi xác nhận bước 1)
```

`CHUYENKHO` là vị trí **internal nằm ngang Tồn kho** (con trực tiếp của vị trí view của kho):
- tính vào tồn của kho nguồn cho tới khi bước 2 được xác nhận;
- đơn bán / phiếu lấy hàng không lấy được (PICK chỉ lấy trong `lot_stock_id`);
- chỉ chọn được trên phiếu chuyển nội bộ (không phải PICK/PACK).

Vị trí cũ `Physical Locations/Inter-warehouse transit` (usage `transit`) vẫn được nhận diện để các phiếu tạo trước khi đổi đi hết.

## 2. Cấu trúc
```
deltatech_picking_transit/
├── data/transfer_location_data.xml   ← <function> tạo CHUYENKHO cho mọi kho mỗi lần nâng cấp
├── models/
│   ├── stock_location.py             ← field hlv_is_transfer_location; stock.warehouse._hlv_get_transfer_location()
│   ├── stock_picking.py              ← tạo bước 2, nhận diện transit/CHUYENKHO, ràng buộc, domain chọn vị trí
│   └── stock_picking_type.py         ← two_step_transfer_use, auto_second_transfer
├── views/                            ← nút "Tạo phiếu bước 2", "Phân bổ lại vị trí"
└── wizard/                           ← wizard tạo bước 2 thủ công
```

## 3. File nào giữ logic nào (không viết lại ở module khác)
| Logic | Nơi duy nhất |
|---|---|
| Lấy/tạo CHUYENKHO của một kho | `stock.warehouse._hlv_get_transfer_location()` |
| Vị trí có phải trung chuyển (CHUYENKHO hoặc Transit cũ) | `stock.picking._is_inter_warehouse_transit(location)` |
| Chặn CHUYENKHO trên phiếu không phải chuyển nội bộ | `stock.picking._check_hlv_transfer_location` + domain field `location_id/location_dest_id` |
| Sinh phiếu bước 2 | `stock.picking.button_validate` → `create_second_transfer_wizard` |
| Tự chọn đích CHUYENKHO khi Liên hệ là kho khác; nguồn bước 2 = đích bước 1 | `stock.picking._compute_location_id` (override) |
| Chặn xác nhận khi nguồn/đích không khớp kho của loại phiếu | `stock.picking._hlv_check_transfer_route` (gọi đầu `button_validate`) |

Module dùng CHUYENKHO (đều `depends` module này): `hlv_mobile_barcode` (`_transfer_location_for`), `hlv_sale_delivery_planning` (phiếu luân chuyển + loại khỏi tồn khả dụng), `misa_fetch_po_button` (`_get_transit_location(from_loc)`), `hlv_stock_origin_audit` (cảnh báo tồn đọng), `hlv_inventory_group_report` (cột sắp giao/chuyển kho).

## 4. Luồng chính
1. Phiếu INT có đích là CHUYENKHO/Transit → bắt buộc có **Liên hệ** = địa chỉ kho nhận.
2. `button_validate`: tìm kho nhận theo Liên hệ, chọn loại phiếu internal của kho nhận (ưu tiên `two_step_transfer_use='reception'`, loại PICK/PACK), lấy `default_location_dest_id` làm đích.
3. Sau khi validate xong: `create_second_transfer_wizard` tạo phiếu bước 2 nguồn = đích bước 1, copy move line (kể cả kiện), confirm, ghi chatter 2 chiều.
4. Kiểm tra trước khi xác nhận (`_hlv_check_transfer_route`, bỏ qua phiếu trả hàng và PICK/PACK):
   - Bước 1: nguồn (header + move line) thuộc kho của loại phiếu; đích thuộc kho đó (CHUYENKHO). Đi thẳng sang kho khác bị chặn. Transit cũ vẫn cho qua.
   - Bước 2: nguồn đúng bằng đích của bước 1; đích thuộc kho của loại phiếu (kho nhận).
5. `write`/`read`/`_onchange_picking_type` giữ nguyên `location_id` của phiếu bước 2 = vị trí trung chuyển.

## 5. Mở rộng
- Thêm kho mới: chạy nâng cấp module hoặc gọi `_hlv_get_transfer_location()` (tự tạo khi thiếu).
- Cho thêm loại phiếu được dùng CHUYENKHO: sửa `_check_hlv_transfer_location`.
