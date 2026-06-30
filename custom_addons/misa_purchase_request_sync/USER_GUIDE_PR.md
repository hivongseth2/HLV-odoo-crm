# TÀI LIỆU HƯỚNG DẪN SỬ DỤNG: PHÂN HỆ YÊU CẦU MUA HÀNG (PURCHASE REQUEST)

Tài liệu này cung cấp hướng dẫn chi tiết quy trình thao tác trên phân hệ **Yêu cầu mua hàng** của hệ thống Odoo, bao gồm việc khởi tạo, phê duyệt và chuyển tiếp sang Đơn mua hàng (PO).

---

## PHẦN 1: KHỞI TẠO YÊU CẦU MUA HÀNG (Dành cho Người yêu cầu)

Bước này được thực hiện bởi Cán bộ nhân viên (CBNV) hoặc các Phòng ban có nhu cầu mua sắm vật tư, trang thiết bị (hoặc dữ liệu được đồng bộ tự động từ MISA AMIS CRM).

### 1. Truy cập phân hệ và Tạo mới
1. Đăng nhập vào hệ thống Odoo.
2. Tại màn hình chính (App Dashboard), chọn ứng dụng **Purchase Requests** (Yêu cầu mua hàng).
3. Hệ thống hiển thị danh sách các Yêu cầu mua hàng hiện có. Nhấn nút **[Mới]** (New) ở góc trái màn hình để khởi tạo chứng từ mới.

### 2. Cập nhật Thông tin chung (General Information)
Phần này bao gồm các thông tin tổng quan của chứng từ:

- **Tên Yêu cầu (Purchase Request):** Mã định danh của chứng từ. Hệ thống có thể tự động cấp mã (VD: `PR00001`) hoặc người dùng có thể tự định nghĩa theo quy tắc nội bộ.
- **Người yêu cầu (Requested by):** Tài khoản nhân viên đề xuất mua sắm (Hệ thống mặc định lấy tài khoản đang đăng nhập).
- **Đơn bán hàng liên quan:** *(Trường thông tin mở rộng)* Nếu Yêu cầu mua hàng này phục vụ cho một đơn hàng cụ thể (từ hệ thống CRM), vui lòng chọn hoặc nhập mã Đơn bán hàng (Sale Order) để thuận tiện cho việc đối chiếu và truy xuất nguồn gốc.
- **Địa điểm giao:** *(Trường thông tin mở rộng)* Cập nhật địa điểm thực tế mà hàng hóa cần được tập kết hoặc giao nhận (VD: Kho công trình A, Trụ sở chính...).
- **Ngày yêu cầu (Request Date):** Ngày lập phiếu.
- **Ngày tạo / Ngày sửa:** Hệ thống tự động ghi nhận thời điểm khởi tạo và thời điểm cập nhật chứng từ gần nhất.

### 3. Cập nhật Danh sách hàng hóa (Products)
Tại khu vực nửa dưới màn hình, chọn thẻ **Hàng hóa (Products)** để khai báo chi tiết vật tư cần mua:

1. Nhấn **[Thêm một dòng]** (Add a line).
2. **Sản phẩm (Product):** Lựa chọn vật tư/hàng hóa cần mua từ danh mục hệ thống.
3. **Mô tả (Description):** Cập nhật chi tiết về quy cách kỹ thuật, màu sắc, chất liệu (nếu cần thiết).
4. **Số lượng (Quantity):** Nhập số lượng dự kiến mua.
5. **ĐVT (UoM):** Đơn vị tính hợp lệ của sản phẩm.
6. **Ngày mong muốn (Expected Date):** Thời hạn muộn nhất yêu cầu hàng hóa phải được bàn giao.

### 4. Lưu và Gửi phê duyệt
- Sau khi nhập liệu, chứng từ sẽ ở trạng thái **Nháp (Draft)**. Ở trạng thái này, người dùng có toàn quyền chỉnh sửa hoặc xóa chứng từ.
- Khi chứng từ đã hoàn thiện, nhấn nút **[Yêu cầu phê duyệt]** (Request Approval) để chuyển tiếp lên Cấp Quản lý.
- Lúc này, chứng từ sẽ chuyển sang trạng thái **Chờ phê duyệt (To Approve)**. Các trường dữ liệu quan trọng sẽ bị khóa để đảm bảo tính toàn vẹn của thông tin.

---

## PHẦN 2: QUY TRÌNH PHÊ DUYỆT (Dành cho Cấp Quản lý)

Bước này được thực hiện bởi Cấp Quản lý hoặc nhân sự được ủy quyền phê duyệt Yêu cầu mua hàng.

### 1. Kiểm tra danh sách chờ phê duyệt
1. Truy cập ứng dụng **Purchase Requests**.
2. Sử dụng bộ lọc **Chờ phê duyệt (To Approve)** trên thanh tìm kiếm để tra cứu các chứng từ cần xử lý.
3. Nhấn vào từng chứng từ để xem xét chi tiết: thông tin người yêu cầu, mục đích mua sắm, Đơn bán hàng liên quan và danh mục hàng hóa cụ thể.

### 2. Các thao tác xử lý
Người có thẩm quyền sẽ thực hiện một trong hai thao tác sau tại góc trên bên trái của chứng từ:

#### Tùy chọn A: Phê duyệt (Approve)
- **Công dụng:** Chấp thuận nội dung Yêu cầu mua hàng.
- **Cách thực hiện:** Nhấn nút **[Phê duyệt]** (Approve).
- **Kết quả:** Trạng thái chứng từ chuyển thành **Đã phê duyệt (Approved)**. Bộ phận Mua hàng (Purchasing) sẽ nhận được thông báo để bắt đầu quy trình tìm kiếm nhà cung cấp và đặt hàng.

#### Tùy chọn B: Từ chối (Reject)
- **Công dụng:** Không chấp thuận Yêu cầu mua hàng (có thể do sai sót về số lượng, không hợp lý về nhu cầu hoặc vượt ngân sách).
- **Cách thực hiện:** Nhấn nút **[Từ chối]** (Reject).
- **Kết quả:** Trạng thái chứng từ chuyển thành **Đã từ chối (Rejected)**. Quy trình xử lý chứng từ này sẽ dừng lại.
- **Lưu ý:** Người yêu cầu có thể kiểm tra lại chứng từ bị từ chối và nhấn nút **[Thiết lập về Nháp]** (Reset to Draft) để điều chỉnh thông tin theo phản hồi của Quản lý, sau đó gửi yêu cầu phê duyệt lại từ đầu.

---

## PHẦN 3: TẠO ĐƠN MUA HÀNG VÀ THEO DÕI TIẾN ĐỘ (Dành cho Bộ phận Mua hàng & Kho)

Sau khi Yêu cầu mua hàng được **Đã phê duyệt (Approved)**, Bộ phận Mua hàng sẽ tiếp nhận thông tin để làm việc với Nhà cung cấp và lập Đơn mua hàng (PO).

### Bước 1: Khởi tạo Yêu cầu báo giá (RFQ) từ YCMH
1. Mở Yêu cầu mua hàng đã được phê duyệt.
2. Nhấn nút **[Tạo Yêu cầu báo giá]** (Create RFQ) ở góc trên bên trái.
3. Hệ thống sẽ hiển thị cửa sổ **"Tạo Yêu cầu báo giá"**. Người dùng cần lưu ý hai phân vùng thông tin sau:

   **A. Phân vùng "RFQ HIỆN CÓ ĐỂ CẬP NHẬT" (Gộp vào Đơn mua hàng đã tồn tại):**
   Sử dụng khi bạn muốn bổ sung các mặt hàng này vào một Đơn mua hàng (PO) đang trong quá trình thực hiện.
   - **Đơn đặt hàng:** Chọn Đơn mua hàng (PO) có sẵn mà bạn muốn gộp chung. Nếu bạn muốn tạo mới hoàn toàn, vui lòng **để trống** trường thông tin này.
   - **Chỉ gộp nếu trùng:** Tùy chọn nâng cao cho phép Odoo tự động tìm và gộp các mặt hàng giống nhau thành một dòng duy nhất trên Đơn mua hàng.
   - **Ngày dự kiến:** Hệ thống tự động tham chiếu Ngày mong muốn giao hàng từ YCMH.

   **B. Phân vùng "CHI TIẾT ĐƠN MUA HÀNG MỚI" (Tạo Đơn mua hàng mới):**
   Sử dụng khi trường "Đơn đặt hàng" ở trên được để trống.
   - **Nhà cung cấp:** Nhập và chọn Nhà cung cấp dự kiến. Đây là trường thông tin bắt buộc khi tạo mới.

   **C. Danh sách hàng hóa đề xuất:**
   Hiển thị danh sách các mặt hàng được trích xuất từ YCMH.
   - Bạn có thể điều chỉnh **Số lượng cần mua** trực tiếp trên danh sách (Ví dụ: Yêu cầu 10 nhưng lần này chỉ đặt mua trước 5, phần còn lại sẽ tạo RFQ trong lần sau).
   - Thiết lập cấu hình (Nút gạt):
     - **Lấy mô tả từ YCMH:** Kích hoạt nếu muốn kế thừa toàn bộ nội dung mô tả của sản phẩm từ YCMH sang Đơn mua hàng.
     - **Lấy giá dự toán:** Kích hoạt nếu muốn sử dụng chi phí ước tính làm giá mua dự kiến (Thông thường sẽ tắt để Bộ phận Mua hàng chủ động thương lượng giá thực tế với Nhà cung cấp).
   - **Thao tác xóa (Biểu tượng thùng rác):** Nhấn để loại bỏ mặt hàng khỏi đợt đặt hàng này. (Mặt hàng bị loại bỏ vẫn sẽ được lưu trữ trên YCMH để đặt mua trong các đợt tiếp theo).

4. Sau khi kiểm tra thông tin, nhấn nút **[Tạo RFQ]** ở góc dưới bên trái cửa sổ để hoàn tất.

### Bước 2: Hoàn thiện Đơn mua hàng (PO)
1. Sau khi Tạo RFQ thành công, góc trên bên phải của phiếu YCMH sẽ xuất hiện Nút truy cập nhanh (Smart Button) có biểu tượng hình xe tải với nhãn **[Đơn mua hàng]** (RFQs/Orders), kèm theo số lượng Đơn mua hàng đã được tạo.
2. Nhấn vào nút truy cập nhanh này để chuyển hướng đến Đơn mua hàng (RFQ) vừa khởi tạo.
3. Tại giao diện Đơn mua hàng, nhân viên mua hàng cập nhật đơn giá đã thương lượng, áp dụng thuế suất tương ứng và xác nhận các điều khoản thanh toán.
4. Khi đã đạt được thỏa thuận cuối cùng với Nhà cung cấp, nhấn nút **[Xác nhận Đơn hàng]** (Confirm Order) để chuyển từ trạng thái Báo giá sang Đơn mua hàng chính thức (PO).

### Bước 3: Nhập kho và Ghi nhận tiến độ
1. Khi Đơn mua hàng được Xác nhận, hệ thống Odoo sẽ tự động phát sinh một chứng từ **Phiếu Nhận Hàng (Receipt)**, có thể truy cập qua nút thông minh ở góc phải Đơn mua hàng.
2. Thủ kho kiểm tra thực tế, truy cập vào Phiếu nhận hàng, cập nhật số lượng thực nhập vào cột **Hoàn thành (Done)** và nhấn **[Xác nhận]** (Validate).
3. **Đồng bộ tiến độ tự động:** Ngay khi thao tác Nhập kho được xác nhận, số lượng hàng hóa đã nhận sẽ được tự động cộng dồn và cập nhật ngược về YCMH ban đầu (Đồng thời tự động đồng bộ về hệ thống MISA CRM nếu YCMH có nguồn gốc từ CRM). 

> **Ghi chú tiện ích:** Tại giao diện của YCMH, trong thẻ **Hàng hóa (Products)**, người dùng có thể giám sát tiến độ mua sắm theo thời gian thực thông qua các trường thông tin:
> - *Số lượng yêu cầu (Quantity)*: Tổng nhu cầu ban đầu.
> - *Số lượng đã lên đơn (Purchased Quantity)*: Khối lượng đã được Bộ phận Mua hàng lập PO.
> - *Trạng thái mua hàng*: Đánh giá mức độ hoàn thành của từng mặt hàng.
