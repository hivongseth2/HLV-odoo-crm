# AMIS Purchase Sync Notes

Tài liệu này ghi lại các điểm quan trọng của luồng đồng bộ mua hàng từ Odoo sang AMIS Kế toán trong module `amis_callback`.

## Luồng chính

1. Khi `purchase.order` được xác nhận, Odoo enqueue job `direction='purchase_order'`.
2. Job đẩy Đơn mua hàng sang MISA bằng endpoint:
   `POST /apir/sync/actopen/save`
3. Payload Đơn mua hàng dùng:
   - `voucher_type = 21`
   - `org_reftype = reftype = 301`
   - object MISA: `pu_order`
4. Khi `stock.picking` nhập kho từ PO được validate, Odoo enqueue job `direction='incoming'`.
5. Job đẩy Chứng từ mua hàng nhập kho sang MISA bằng cùng endpoint `save`.
6. Payload phiếu nhập dùng:
   - `voucher_type = 18`
   - `org_reftype = reftype = 302`
   - object MISA: `pu_voucher`
   - loại chứng từ: Mua hàng trong nước nhập kho chưa thanh toán
   - `include_invoice = 0` khi nhập kho không kèm hóa đơn mua hàng

Lưu ý: mẫu tài liệu MISA cho `pu_voucher` có `pu_invoice_refid` khi gửi kèm object
`pu_invoice` (`voucher_type = 15`). Trường này là ID hóa đơn mua hàng, không phải ID
đơn mua hàng. Với luồng nhập kho từ PO chưa kèm hóa đơn, không tự sinh hoặc gán giả
`pu_invoice_refid`.

`purchase_purpose_id` là Nhóm HHDV mua vào. Nếu cache hàng hóa MISA không có giá trị
riêng, module dùng mặc định mã 1 theo tài liệu MISA:
`ed4bd91d-83ac-4a26-b4c1-4bce85faecb8`.

## Link phiếu nhập về đơn mua

Có 2 lớp liên kết cần phân biệt:

1. Header `reference`

   Dùng để UI MISA hiển thị mục **Tham chiếu** giữa phiếu nhập và đơn mua.

   ```json
   {
     "org_refid": "<org_refid phieu nhap>",
     "org_refno": "<so phieu nhap>",
     "org_reftype": 302,
     "org_refer_refid": "<org_refid don mua>",
     "org_refer_refno": "<so don mua>",
     "org_refer_reftype": 301
   }
   ```

2. Detail link trên `pu_voucher_detail`

   Dùng để MISA cộng dồn **Số lượng nhận** trên Đơn mua hàng.

   ```json
   {
     "pu_order_refid": "<refid don mua>",
     "pu_order_ref_detail_id": "<ref_detail_id dong don mua>",
     "pu_order_refno": "<so don mua>",
     "purchase_purpose_id": "<nhom HHDV mua vao neu co>",
     "quantity": 30
   }
   ```

Chỉ có `reference` thì MISA vẫn hiện tham chiếu trên UI, nhưng chưa đủ để cập nhật số lượng nhận trên dòng Đơn mua hàng.

## Quy tắc bắt buộc: `is_get_new_id = false`

Với luồng này, cả Đơn mua hàng (`pu_order`) và phiếu nhập (`pu_voucher`) phải dùng:

```json
"is_get_new_id": false
```

Lý do:

- Callback MISA chỉ trả `org_refid`, không trả đầy đủ `refid/ref_detail_id` thật của chứng từ và dòng chi tiết.
- Nếu để `is_get_new_id=true`, MISA có thể tự sinh ID nội bộ khác với ID Odoo gửi.
- Header `reference` vẫn có thể hoạt động vì dùng `org_refid`.
- Nhưng phần cộng dồn số lượng nhận dựa vào detail link `pu_order_refid` + `pu_order_ref_detail_id`; nếu identity chứng từ/dòng không đồng nhất, nhiều phiếu nhập có thể không cộng tiếp vào PO.

Kết luận đã test:

- PO dùng `is_get_new_id=false`, phiếu nhập còn `is_get_new_id=true`: MISA có thể chỉ cộng phiếu nhập đầu hoặc không cộng ổn định.
- PO và phiếu nhập đều dùng `is_get_new_id=false`: MISA cộng dồn đúng nhiều phiếu nhập vào cùng một Đơn mua hàng.

## Các field liên quan trong code

- `purchase.order.misa_purchase_order_org_refid`: `refid/org_refid` gửi cho `pu_order`.
- `purchase.order.line.misa_purchase_order_org_ref_detail_id`: `ref_detail_id` gửi cho dòng `pu_order_detail`.
- `stock.picking.misa_inward_org_refid`: `refid/org_refid` gửi cho `pu_voucher`.
- `stock.move.misa_ref_detail_id`: `ref_detail_id` gửi cho dòng `pu_voucher_detail`.
- `stock.move.misa_inward_ref_detail_id`: `ref_detail_id` riêng của dòng phiếu nhập.
- `stock.move.misa_inward_po_refid`: `pu_order_refid` gửi trên dòng phiếu nhập.
- `stock.move.misa_inward_po_ref_detail_id`: `pu_order_ref_detail_id` gửi trên dòng phiếu nhập.
- `stock.move.misa_purchase_purpose_id`: `purchase_purpose_id` gửi trên dòng phiếu nhập.

## File code chính

- `models/purchase_order_sync.py`
  - Chuẩn bị payload `pu_order`.
  - Sinh deterministic `refid/ref_detail_id` cho PO và PO line.
  - Bắt buộc `is_get_new_id=false`.

- `models/stock_picking_sync.py`
  - Chuẩn bị payload `pu_voucher`.
  - Gửi `reference` header với `org_reftype=302`.
  - Gửi `pu_order_refid`, `pu_order_ref_detail_id` ở từng dòng phiếu nhập.
  - Gửi `pu_order_refid`, `pu_order_refno` ở header để MISA có ngữ cảnh đơn mua gốc.
  - Gửi `purchase_purpose_id`/`purchase_purpose_code` từ cache hàng hóa MISA hoặc fallback mã 1.
  - Lưu các ID dòng trên `stock.move` để retry/debug không phải đoán lại payload.
  - Bắt buộc `is_get_new_id=false`.

- `models/amis_callback_config.py`
  - Gọi `/apir/sync/actopen/save`.
  - Log payload/response cho PO và phiếu nhập để debug.

## Debug nhanh

Khi số lượng nhận không cộng đúng trên MISA, kiểm tra log:

```text
Push MISA inward <picking>: org_refid=<...>, po=<PO>, po_refid=<...>, detail_links=<item> qty=<...> inward_detail=<...> po_detail=<...>
```

Cần xác nhận:

- `po_refid` của mọi phiếu nhập cùng PO phải giống nhau.
- `po_detail` của cùng một dòng hàng phải giống nhau qua các lần nhập.
- `inward_detail` của từng phiếu nhập phải khác nhau.
- Payload `AMIS save purchase order payload` có `is_get_new_id=false`.
- Payload `AMIS save inward payload` có `is_get_new_id=false`.

