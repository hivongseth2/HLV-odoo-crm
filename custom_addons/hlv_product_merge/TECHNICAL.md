# HLV Product Merge

Module độc lập để gộp tồn của một `product.product` vào sản phẩm gốc và lưu trữ
sản phẩm nguồn. Module không phụ thuộc `amis_callback`.

## Cách dùng

Người thuộc nhóm **Quản lý kho** mở danh sách Sản phẩm hoặc Biến thể sản phẩm:

1. Chọn một sản phẩm, vào **Hành động → Gộp sản phẩm**, rồi chọn sản phẩm nguồn;
   hoặc chọn sẵn đúng hai sản phẩm trước khi mở hành động.
2. Kiểm tra lại sản phẩm gốc và sản phẩm sẽ được gộp.
3. Nếu hai ĐVT khác nhau, kiểm tra số lượng đích đã được điền ban đầu bằng tồn
   nguồn và chỉnh lại trên từng dòng vị trí/lô khi tỷ lệ không phải 1:1.
4. Đánh dấu xác nhận và bấm **Gộp sản phẩm**.

## Điều kiện chặn

Sản phẩm nguồn không được còn:

- đơn bán chưa giao đủ;
- đơn mua chưa nhận đủ;
- phiếu kho/chuyển kho chưa hoàn tất;
- số lượng đang giữ chỗ;
- tồn hoặc chứng từ thuộc công ty ngoài phạm vi công ty đang bật.

Ngay trước khi chuyển, module đọc lại toàn bộ `stock.quant`. Nếu vị trí hoặc số
lượng đã thay đổi từ lúc mở wizard, giao dịch bị hủy và người dùng phải mở lại.

## Dữ liệu được chuyển

Tồn được chuyển theo đúng các chiều:

- vị trí;
- lô/serial;
- kiện;
- chủ sở hữu;
- công ty.

Wizard gom các quant có cùng vị trí và lô/serial thành một dòng. Khi xác nhận,
số lượng đích của dòng được phân bổ theo tỷ lệ về các package/owner gốc để vẫn
giữ đúng các chiều tồn kho bên dưới.

Nếu sản phẩm gốc theo dõi lô, module tạo/tái sử dụng lô cùng tên cho sản phẩm
gốc. Với serial, mỗi dòng chỉ được quy đổi thành một đơn vị.

Sau khi thành công, sản phẩm nguồn được lưu trữ và ghi các trường audit
`hlv_merged_into_product_id`, `hlv_merged_at`, `hlv_merged_by_id`,
`hlv_merge_note`. Chatter của cả hai sản phẩm lưu link chéo và chi tiết tồn đã
chuyển.

## Lưu ý kỹ thuật

Logic chuyển tồn dùng API nội bộ `stock.quant._update_available_quantity`, giống
luồng xử lý ĐVT đã có trong AMIS callback nhưng được triển khai riêng, không import
hay gọi model AMIS. Vì đây là thao tác thay đổi trực tiếp số lượng tồn, nên cần
backup và kiểm thử trên staging theo phương pháp định giá tồn kho thực tế trước
khi bật trên production.
