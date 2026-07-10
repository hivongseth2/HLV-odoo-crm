# Mô tả module và SOP sử dụng HLV Loyalty

## 1. Mục đích

`hlv_loyalty` là module quản lý khách hàng thân thiết trên Odoo, kết nối quy trình bán hàng, giao hàng, tích điểm, xếp hạng thành viên và đổi thưởng.

Mỗi nhân viên kinh doanh có thể phụ trách nhiều khách hàng theo trường **Nhân viên kinh doanh** trên hồ sơ khách hàng của Odoo. Với từng khách hàng, hệ thống quản lý:

- Tài khoản đăng nhập trang Loyalty.
- Điểm xếp hạng.
- Điểm đổi thưởng.
- Điểm chờ xác nhận và điểm đang treo.
- Hạng thành viên, lịch sử điểm, voucher và yêu cầu đổi thưởng.

Trang khách hàng: <https://www.hoanglongvu-erp.com/loyalty>

## 2. Phân biệt các loại điểm

| Loại điểm | Cách phát sinh | Trạng thái ban đầu | Mục đích |
|---|---|---|---|
| **Điểm xếp hạng** | Tính theo doanh số hàng thực giao | Tự động xác nhận | Xác định hạng Đồng, Bạc, Vàng, Kim cương |
| **Điểm đổi thưởng** | Tính theo khoản chiết khấu Loyalty do sale khai báo trên dòng đơn hàng | Chờ xác nhận | Đổi quà, voucher hoặc tiền mặt |

Hai loại điểm độc lập:

- Khách hàng chỉ dùng **điểm đổi thưởng đã xác nhận** để đổi thưởng.
- Duyệt yêu cầu đổi tiền chỉ trừ **điểm đổi thưởng**; không trừ điểm xếp hạng.
- Điểm xếp hạng vẫn được giữ để xác định hạng thành viên, trừ trường hợp có nghiệp vụ hoàn hàng.

Hệ thống còn hiển thị hai khái niệm cần phân biệt:

- **Điểm chờ xác nhận:** điểm đổi thưởng vừa phát sinh từ giao hàng, chưa được người quản lý duyệt nên chưa thể sử dụng.
- **Điểm đang treo:** điểm đổi thưởng đã khả dụng nhưng đang nằm trong một yêu cầu đổi thưởng chờ xử lý. Điểm chưa bị trừ khỏi sổ điểm, nhưng bị giữ lại và không thể dùng cho yêu cầu khác.

## 3. Luồng nghiệp vụ tổng quát

```text
Sale quản lý khách hàng và tài khoản Loyalty
    → Lập báo giá/đơn bán
    → Nhập CK Loyalty (%) trên từng dòng hàng
    → Kho hoàn tất phiếu xuất
        → Điểm xếp hạng: tự động cộng
        → Điểm đổi thưởng: tạo ở trạng thái Chờ xác nhận
    → Người quản lý Loyalty xác nhận điểm đổi thưởng
    → Khách đăng nhập /loyalty
    → Khách gửi yêu cầu đổi tiền và thông tin nhận tiền
    → Điểm yêu cầu được treo
    → Người quản lý kiểm tra, chuyển khoản và đánh dấu đã xử lý
    → Hệ thống trừ điểm đổi thưởng và hoàn tất yêu cầu
```

## 4. Vai trò và trách nhiệm

### 4.1. Nhân viên kinh doanh

- Quản lý danh sách khách hàng được phân công trên Odoo.
- Kiểm tra thông tin khách hàng và tài khoản Loyalty.
- Lập báo giá/đơn bán.
- Nhập đúng tỷ lệ **CK Loyalty (%)** trên từng dòng sản phẩm.
- Phối hợp xử lý khi đơn hàng, giao hàng hoặc điểm phát sinh sai.

### 4.2. Nhân viên kho

- Xử lý và xác nhận đúng số lượng thực giao.
- Hoàn tất phiếu xuất kho để hệ thống phát sinh điểm.

### 4.3. Người quản lý Loyalty

Người dùng cần được cấp tối thiểu quyền **Loyalty / Xử lý**.

- Tạo, kích hoạt và reset tài khoản Loyalty cho khách hàng.
- Kiểm tra và xác nhận điểm đổi thưởng phát sinh từ giao hàng.
- Tiếp nhận yêu cầu đổi tiền.
- Đối chiếu điểm, thông tin ngân hàng và lịch sử khách hàng.
- Chuyển khoản, ghi chú đối soát và đánh dấu yêu cầu đã xử lý.
- Hủy yêu cầu không hợp lệ.

### 4.4. Khách hàng

- Đăng nhập trang Loyalty.
- Theo dõi điểm, hạng thành viên, lịch sử và voucher.
- Gửi hoặc hủy yêu cầu đổi tiền khi yêu cầu vẫn đang chờ xử lý.
- Tự bảo mật và thay đổi mật khẩu.

## 5. Điều kiện để đơn hàng phát sinh điểm

Điểm chỉ được tạo khi đáp ứng đủ các điều kiện:

1. Phiếu kho là phiếu giao hàng cho khách.
2. Phiếu giao hàng có liên kết với đơn bán.
3. Phiếu đã được hoàn tất.
4. Khách hàng gốc có tài khoản Loyalty đang hoạt động.
5. Hệ thống có chương trình Loyalty đang hoạt động.
6. Phiếu giao hàng chưa phát sinh giao dịch tích điểm trước đó.

Nếu tạo tài khoản Loyalty sau khi phiếu giao hàng đã hoàn tất, hệ thống không tự động hồi tố điểm. Người có quyền phù hợp phải dùng chức năng **Tính lại điểm Loyalty**.

## 6. SOP dành cho nhân viên kinh doanh

### Bước 1: Gán khách hàng cho sale phụ trách

1. Vào **Liên hệ**.
2. Mở hồ sơ khách hàng.
3. Chọn đúng **Nhân viên kinh doanh** phụ trách.
4. Kiểm tra tên công ty, số điện thoại và email.

Điểm và tài khoản Loyalty được quản lý tại khách hàng gốc. Các đơn của liên hệ/công ty con có thể cộng điểm về khách hàng gốc.

### Bước 2: Kiểm tra tài khoản Loyalty

Trước khi giao hàng:

1. Mở hồ sơ khách hàng gốc.
2. Vào tab Loyalty và kiểm tra **Tài khoản Portal**.
3. Đảm bảo tài khoản ở trạng thái hoạt động.
4. Nếu chưa có tài khoản, chuyển yêu cầu cho người có quyền **Loyalty / Xử lý** để tạo.

Khách có thể đăng nhập bằng tên đăng nhập hoặc số điện thoại đăng nhập đã cấu hình.

### Bước 3: Lập báo giá/đơn bán

1. Từ CRM hoặc Bán hàng, tạo báo giá/đơn bán cho đúng khách hàng.
2. Thêm các dòng sản phẩm.
3. Tại từng dòng hàng, nhập **CK Loyalty (%)**.

Quy tắc nhập:

- Nhập `5` nghĩa là `5%`.
- Đây là tỷ lệ dùng để tính điểm đổi thưởng.
- Trường này không tự làm giảm giá bán hoặc thành tiền trên đơn hàng.
- Nếu dòng hàng không có CK Loyalty, hệ thống có thể dùng tỷ lệ mặc định trên khách hàng khi toàn bộ đơn không phát sinh khoản chiết khấu Loyalty theo dòng.

### Bước 4: Xác nhận đơn và giao hàng

1. Xác nhận báo giá thành đơn bán.
2. Nhân viên kho mở phiếu giao hàng.
3. Nhập đúng số lượng thực giao.
4. Bấm **Xác nhận/Validate** để hoàn tất phiếu xuất.

Ngay khi phiếu xuất hoàn tất:

- Điểm xếp hạng được tạo ở trạng thái **Đã xác nhận** và cộng ngay.
- Điểm đổi thưởng được tạo ở trạng thái **Chờ xác nhận**.

## 7. Cách hệ thống tính điểm

### 7.1. Điểm xếp hạng

```text
Điểm xếp hạng
    = phần nguyên(Doanh số thực giao / Số tiền tích lũy quy đổi)
      × Số điểm nhận được mỗi mốc
```

Các tham số được khai báo trong chương trình Loyalty. Cấu hình mặc định trong mã là 100.000 đồng tương ứng 1 điểm, nhưng phải dùng giá trị đang cấu hình thực tế trên hệ thống.

### 7.2. Điểm đổi thưởng

Với mỗi dòng giao hàng:

```text
Khoản CK Loyalty
    = Đơn giá × Số lượng thực giao × CK Loyalty (%)

Điểm đổi thưởng
    = phần nguyên(Tổng khoản CK Loyalty / Số tiền chiết khấu cho 1 điểm)
```

Ví dụ theo cấu hình 10.000 đồng chiết khấu bằng 1 điểm:

```text
Giá trị hàng thực giao: 10.000.000 đồng
CK Loyalty: 5%
Khoản CK Loyalty: 500.000 đồng
Điểm đổi thưởng phát sinh: 50 điểm
```

## 8. SOP xác nhận điểm đổi thưởng sau xuất kho

Người thực hiện: người có quyền **Loyalty / Xử lý**.

1. Vào **Loyalty → Quản lý → Lịch sử điểm**.
2. Lọc:
   - **Loại điểm:** Điểm đổi thưởng.
   - **Trạng thái:** Chờ xác nhận.
   - Có thể tìm thêm theo khách hàng, đơn bán hoặc phiếu kho.
3. Mở giao dịch cần kiểm tra.
4. Đối chiếu:
   - Khách hàng.
   - Đơn bán và phiếu giao hàng.
   - Số lượng thực giao.
   - Tỷ lệ CK Loyalty.
   - Công thức và số điểm phát sinh.
5. Nếu đúng, bấm **Xác nhận điểm**.
6. Nếu không hợp lệ, bấm **Hủy** và phối hợp bộ phận liên quan kiểm tra lại đơn.

Sau khi xác nhận, điểm được cộng vào **Điểm đổi thưởng** và khách có thể sử dụng trên portal.

## 9. SOP dành cho khách hàng đổi điểm thành tiền

1. Truy cập <https://www.hoanglongvu-erp.com/loyalty>.
2. Đăng nhập bằng tên đăng nhập hoặc số điện thoại và mật khẩu Loyalty.
3. Tại trang tổng quan, kiểm tra:
   - Điểm xếp hạng.
   - Điểm đổi thưởng.
   - Điểm khả dụng.
   - Điểm đang treo hoặc chờ xác nhận.
4. Chọn **Đổi thưởng**.
5. Chọn tab **Đổi tiền mặt**.
6. Nhập **Số điểm muốn đổi**. Số điểm không được vượt quá điểm khả dụng.
7. Nhập đầy đủ:
   - Ngân hàng.
   - Số tài khoản.
   - Tên chủ tài khoản.
   - Ghi chú nếu có.
8. Kiểm tra số tiền dự kiến nhận theo tỷ lệ đang hiển thị.
9. Bấm **Gửi yêu cầu**.
10. Vào tab **Yêu cầu của tôi** để theo dõi trạng thái.

Sau khi gửi:

- Yêu cầu ở trạng thái **Chờ duyệt**.
- Số điểm yêu cầu chuyển thành **điểm đang treo**.
- Điểm chưa bị trừ khỏi sổ điểm, nhưng không thể dùng để tạo yêu cầu khác.
- Khách có thể hủy yêu cầu khi yêu cầu chưa được xử lý.

## 10. SOP xử lý yêu cầu đổi tiền

Người thực hiện: người có quyền **Loyalty / Xử lý**.

1. Vào **Loyalty → Quản lý → Yêu cầu đổi thưởng**.
2. Màn hình mặc định hiển thị các yêu cầu **Chờ duyệt**.
3. Lọc **Loại yêu cầu = Đổi tiền mặt**.
4. Mở yêu cầu và kiểm tra:
   - Mã yêu cầu.
   - Khách hàng.
   - Số điểm yêu cầu.
   - Giá trị tiền quy đổi.
   - Số dư tại thời điểm gửi.
   - Ngân hàng, số tài khoản và tên chủ tài khoản.
   - Ghi chú khách hàng.
   - Lịch sử điểm của khách hàng.
5. Đối chiếu thông tin người nhận tiền theo quy định nội bộ.
6. Thực hiện chuyển khoản.
7. Ghi mã giao dịch hoặc nội dung đối soát vào **Ghi chú xử lý**.
8. Bấm **Đánh dấu đã xử lý** và xác nhận cảnh báo.

Khi bấm **Đánh dấu đã xử lý**, hệ thống thực hiện ngay:

- Kiểm tra lại số dư điểm đổi thưởng.
- Tạo một giao dịch đổi thưởng âm.
- Trừ đúng số **điểm đổi thưởng** của yêu cầu.
- Không thay đổi điểm xếp hạng.
- Lưu người xử lý và thời gian xử lý.
- Chuyển yêu cầu sang **Đã xử lý**.

Nếu yêu cầu không hợp lệ:

1. Ghi rõ lý do vào **Ghi chú xử lý**.
2. Bấm **Hủy yêu cầu**.
3. Điểm đang treo được giải phóng và trở lại điểm khả dụng.

Yêu cầu đã xử lý không thể hủy.

## 11. Kiểm tra và đối soát

### Đối soát điểm phát sinh

- Mỗi phiếu giao hàng chỉ được có tối đa một giao dịch tích điểm xếp hạng và một giao dịch tích điểm đổi thưởng.
- Kiểm tra công thức chi tiết trên giao dịch điểm.
- Điểm đổi thưởng chỉ khả dụng khi giao dịch ở trạng thái **Đã xác nhận**.

### Đối soát đổi tiền

- Yêu cầu đã xử lý phải có:
  - Người xử lý.
  - Ngày xử lý.
  - Giao dịch điểm liên kết.
  - Ghi chú/mã chuyển khoản theo quy định nội bộ.
- Giao dịch điểm liên kết phải là:
  - Loại điểm: **Điểm đổi thưởng**.
  - Loại giao dịch: **Đổi thưởng**.
  - Số điểm âm.
  - Trạng thái: **Đã xác nhận**.

### Trường hợp hoàn hàng

Khi hoàn hàng, module thu hồi điểm tương ứng với tỷ lệ hàng hoàn:

- Điểm xếp hạng bị trừ theo số lượng hoàn.
- Điểm đổi thưởng đang chờ xác nhận có thể bị giảm hoặc hủy.
- Điểm đổi thưởng đã xác nhận sẽ phát sinh giao dịch thu hồi âm.

## 12. Lưu ý về hiện trạng phân quyền

Việc gán một sale phụ trách nhiều khách hàng sử dụng trường **Nhân viên kinh doanh** chuẩn của Odoo. Phiên bản module hiện tại chưa có record rule riêng để bắt buộc sale chỉ được xem dữ liệu Loyalty của khách hàng do mình phụ trách; các màn hình Loyalty đang được thiết kế theo mô hình quản lý tập trung.

Nếu yêu cầu vận hành là mỗi sale chỉ được xem và quản lý tài khoản của khách hàng thuộc mình, cần bổ sung phân quyền theo `res.partner.user_id` và áp dụng đồng bộ cho khách hàng, tài khoản Portal, lịch sử điểm và yêu cầu đổi thưởng.

## 13. Checklist vận hành nhanh

### Sale trước khi giao hàng

- [ ] Khách hàng được gán đúng sale phụ trách.
- [ ] Khách hàng gốc có tài khoản Loyalty đang hoạt động.
- [ ] CK Loyalty (%) được nhập đúng trên từng dòng hàng.
- [ ] Đơn bán và phiếu giao hàng liên kết đúng khách hàng.

### Người quản lý Loyalty sau giao hàng

- [ ] Kiểm tra giao dịch điểm đổi thưởng chờ xác nhận.
- [ ] Đối chiếu đơn bán, phiếu kho, tỷ lệ và công thức.
- [ ] Xác nhận hoặc hủy giao dịch.

### Người quản lý Loyalty khi đổi tiền

- [ ] Kiểm tra yêu cầu đang chờ và loại yêu cầu đổi tiền.
- [ ] Kiểm tra điểm khả dụng và lịch sử điểm.
- [ ] Xác minh thông tin tài khoản ngân hàng.
- [ ] Thực hiện chuyển khoản.
- [ ] Ghi mã đối soát.
- [ ] Đánh dấu đã xử lý để hệ thống trừ điểm đổi thưởng.
