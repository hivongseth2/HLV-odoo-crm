# deltatech_picking_transit — Technical

## 1. Mục đích
Chuyển hàng giữa hai kho theo 2 bước:

```
Bước 1 (CKD kho nguồn):   KBC/Tồn kho      → KBC/CHUYENKHO
Bước 2 (CKN kho nhận):    KBC/CHUYENKHO    → TSN/Stock   (tự sinh khi xác nhận bước 1)
```

Loại phiếu: mỗi kho có **Chuyển kho đi** (CKD, `two_step_transfer_use='delivery'`) và **Nhận chuyển kho** (CKN,
`'reception'`), tạo bằng `bin/create_picking_type_chuyen_kho.py`. Kho chưa có thì bước 1/bước 2 vẫn là INT như trước
khi tách. Phiếu INT cũ (đang dở) chạy bình thường: mọi logic nhận diện chuyển kho theo vị trí CHUYENKHO và
`source_transfer_id`, không theo loại phiếu.

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
│   ├── stock_move.py                 ← giữ nguồn move/move line phiếu bước 2 = CHUYENKHO (helper dùng chung)
│   ├── stock_move_line.py            ← chặn sửa tay Transit / đích sai CHUYENKHO trên từng dòng; giữ nguồn bước 2
│   ├── stock_picking.py              ← tạo bước 2, nhận diện transit/CHUYENKHO, ràng buộc, domain chọn vị trí
│   └── stock_picking_type.py         ← two_step_transfer_use, auto_second_transfer
├── views/                            ← nút "Tạo phiếu bước 2", "Phân bổ lại vị trí"
└── wizard/                           ← wizard tạo bước 2 thủ công
```

## 3. File nào giữ logic nào (không viết lại ở module khác)
| Logic | Nơi duy nhất |
|---|---|
| Lấy/tạo CHUYENKHO của một kho | `stock.warehouse._hlv_get_transfer_location()` |
| Loại phiếu bước 1 của kho (CKD, chưa có thì INT) | `stock.warehouse._hlv_transfer_out_type()` |
| Loại phiếu bước 2 ở kho nhận (CKN, chưa có thì loại nội bộ đi vào tồn, ưu tiên INT) | `stock.warehouse._hlv_transfer_in_type()` |
| Vị trí có phải trung chuyển (CHUYENKHO hoặc Transit cũ) | `stock.picking._is_inter_warehouse_transit(location)` |
| Chặn CHUYENKHO trên phiếu không phải chuyển nội bộ | `stock.picking._check_hlv_transfer_location` + domain field `location_id/location_dest_id` |
| Chặn Transit (nguồn/đích) trên phiếu chuyển nội bộ đang mở, trừ nguồn bước 2 = đích Transit của bước 1 cũ | `stock.picking._hlv_check_no_transit` (gọi từ `_check_hlv_transfer_location` và `stock.move.line._check_hlv_no_transit`) |
| Chuyển sang kho khác (Liên hệ là kho khác / đích là vị trí tồn của kho khác / đích là CHUYENKHO): đích phiếu + từng dòng bắt buộc = CHUYENKHO của kho nguồn; cùng kho hoặc ra vị trí ảo ngoài kho (Xuất kho sử dụng → SUDUNG-*) bỏ qua | `stock.picking._hlv_check_inter_warehouse_dest` (gọi từ 2 ràng buộc trên) |
| Sinh phiếu bước 2 | `stock.picking.button_validate` → `create_second_transfer_wizard` |
| Phần còn lại (backorder) của phiếu bước 2 giữ `source_transfer_id` khi tách trên web | `stock.picking._create_backorder_picking` (override) |
| Tự chọn đích CHUYENKHO khi Liên hệ là kho khác; nguồn bước 2 = đích bước 1 | `stock.picking._compute_location_id` (override) |
| Nguồn move/move line phiếu bước 2 luôn = đích bước 1: create/write đổi `location_id` khác thì ép về (onchange đổi nguồn phiếu của Odoo kéo theo move → move line, `stock.picking.write` chỉ chặn được cấp phiếu) | `stock_move.py` `_hlv_pin_step2_source*` + `stock.picking._hlv_step2_source()`, gọi từ `stock.move`/`stock.move.line` create/write |
| Chặn xác nhận khi nguồn/đích không khớp kho của loại phiếu | `stock.picking._hlv_check_transfer_route` (gọi đầu `button_validate`) |

Module dùng CHUYENKHO (đều `depends` module này): `hlv_mobile_barcode` (`_transfer_location_for`, `_transfer_picking_type` → `_hlv_transfer_out_type`), `hlv_sale_delivery_planning` (phiếu luân chuyển → `_hlv_transfer_out_type` + loại khỏi tồn khả dụng), `misa_fetch_po_button` (`_get_transit_location(from_loc)`, loại phiếu → `_hlv_transfer_out_type`), `hlv_stock_origin_audit` (cảnh báo tồn đọng), `hlv_inventory_group_report` (cột sắp giao/chuyển kho).

## 4. Luồng chính
1. Phiếu nội bộ (CKD, hoặc INT cũ) có đích là CHUYENKHO/Transit → bắt buộc có **Liên hệ** = địa chỉ kho nhận.
2. `button_validate`: tìm kho nhận theo Liên hệ, lấy loại phiếu `warehouse._hlv_transfer_in_type()` của kho nhận (CKN; chưa có thì loại nội bộ đi vào tồn — loại PICK/PACK, CKD và loại đi ra vị trí ảo như Xuất kho sử dụng), lấy `default_location_dest_id` làm đích.
3. Sau khi validate xong: `create_second_transfer_wizard` tạo phiếu bước 2 nguồn = đích bước 1, copy move line (kể cả kiện), confirm, ghi chatter 2 chiều.
4. Kiểm tra trước khi xác nhận (`_hlv_check_transfer_route`, bỏ qua phiếu trả hàng và PICK/PACK):
   - Bước 1: nguồn (header + move line) thuộc kho của loại phiếu; đích thuộc kho đó (CHUYENKHO). Đi thẳng vào vị trí tồn kho khác bị chặn; ra vị trí ảo ngoài kho (SUDUNG-*) cho qua. Transit cũ vẫn cho qua.
   - Bước 2: nguồn đúng bằng đích của bước 1; đích thuộc kho của loại phiếu (kho nhận).
5. `write`/`read`/`_onchange_picking_type` giữ nguyên `location_id` của phiếu bước 2 = vị trí trung chuyển; `stock.move`/`stock.move.line` create/write giữ nguồn từng dòng (người dùng đổi nguồn trên form → lưu → cả phiếu, move, move line đều về CHUYENKHO).

## 5. Mở rộng
- Thêm kho mới: chạy nâng cấp module hoặc gọi `_hlv_get_transfer_location()` (tự tạo khi thiếu).
- Cho thêm loại phiếu được dùng CHUYENKHO: sửa `_check_hlv_transfer_location`.
- Quyền kho (`hlv_warehouse_permission`) nhận diện phiếu bước 2 qua `source_transfer_id`: bỏ CHUYENKHO kho gửi khỏi các kho bị kiểm, không kiểm quyền "tạo" phiếu bước 2 hệ thống sinh. Người nhận chỉ cần CKN ở kho nhận, người gửi chỉ cần CKD ở kho gửi.
- Mã trình tự CKD/CKN gắn với quyền kho (`hlv_warehouse_permission`, `hlv_mobile_barcode` tra quyền theo `sequence_code`) và với `stock_quantity_validation` (bỏ kiểm vượt SL như INT). Đổi mã thì sửa cả các chỗ đó.
- `scripts/migrate_transit_to_chuyenkho.py` (**dự trù, chưa chạy**, không nằm trong module): chuyển phiếu bước 1/bước 2 chưa xong từ Transit cũ sang CHUYENKHO, chạy bằng `odoo-bin shell`, mặc định `DRY_RUN = True`.
