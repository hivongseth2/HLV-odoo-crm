# Technical Document: HLV Mobile Barcode

## Mục đích
Cung cấp một giải pháp quét mã vạch (Barcode Scanner) được tối ưu hóa cho màn hình cảm ứng di động (Mobile Web) trong Odoo 18. Hỗ trợ "Smart Routing" - người dùng không cần chọn trước thao tác, chỉ cần quét mã (Sản phẩm, Vị trí, Lệnh chuyển, Kiện hàng) hệ thống sẽ tự động chuyển đến màn hình tương ứng. Hỗ trợ đầy đủ các tính năng như Lấy hàng, Đóng gói (có in nhãn), Kiểm tra tồn kho và Dịch chuyển vị trí.

## Cấu trúc thư mục (Tree view)
```
hlv_mobile_barcode/
├── controllers/
│   ├── __init__.py
│   └── main.py              ← JSON RPC API cho quá trình quét và xử lý (Smart Routing)
├── models/
│   ├── __init__.py
│   └── res_config_settings.py ← Lưu cấu hình của Barcode App (Picking Types, In nhãn v.v.)
├── static/src/
│   ├── components/          ← Các OWL component chính
│   │   ├── barcode_app/     ← Component cha quản lý state và UI chính (Camera/Scanner)
│   │   ├── inventory_lookup/← UI Tra cứu tồn kho (Product/Location/Package)
│   │   ├── location_move/   ← UI Chuyển vị trí (Dùng API tạo Internal Transfer)
│   │   └── picking_scanner/ ← UI Xử lý lệnh Picking (Lấy/Nhập/Chuyển)
│   └── css/                 ← CSS cho Mobile 
├── views/
│   ├── barcode_menu.xml     ← Action mở ứng dụng OWL (Client Action)
│   └── res_config_settings_views.xml
├── __init__.py
└── __manifest__.py
```

## Kiến trúc Frontend (OWL 2.0)
- `barcode_app`: Component cha lắng nghe sự kiện barcode (`keydown`). Khi nhận mã, gọi Backend RPC `smart_scan`. Dựa vào response, thay đổi trạng thái (`currentView`) để hiển thị Component con tương ứng.
- **Persistent Inline Camera**: Camera được nhúng trực tiếp ở phần trên cùng của ứng dụng để quét liên tục. Hoạt động dựa trên **BarcodeDetector API** (native trên các trình duyệt mới hoặc qua polyfill được tải tự động từ jsdelivr). Quét thông qua vòng lặp `requestAnimationFrame` nhẹ nhàng. Sau mỗi lần quét thành công, camera ghi nhận kết quả và tạm dừng 2 giây đối với mã vạch trùng lặp để tránh trùng lặp thao tác.
  - *Cấu hình Camera mặc định*: Trạng thái Camera mặc định bật/tắt khi vào phiếu (`camera_default_on`) được truy vấn toàn cục từ Backend thông qua API `/hlv_mobile_barcode/get_settings` khi tải ứng dụng, sau đó lưu cache trong `sessionStorage` để khôi phục nhanh khi tải lại trang. Khi người dùng điều hướng sang bất kỳ phiếu kho hoặc màn hình quét nào, trạng thái `cameraManuallyOff` được đồng bộ hóa tức thì từ cấu hình này nhằm triệt tiêu hoàn toàn lỗi Race Condition (camera bật lên trước khi cấu hình tải xong).
- **Xử lý Quyền & Bảo mật Camera di động**:
  - *HTTPS Context*: Kiểm tra `window.isSecureContext`. Nếu truy cập qua HTTP (không bảo mật), hệ thống tự động tắt camera trực tiếp và hiển thị thông báo yêu cầu HTTPS, đồng thời kích hoạt fallback (chụp ảnh bằng file input).
  - *iOS / Safari / Chrome User Gesture*: Để tránh việc hệ thống iOS (WKWebView) tự động từ chối (`NotAllowedError`) khi gọi camera tự động lúc tải trang (`onMounted`), component sẽ hiển thị một lớp phủ "Kích hoạt Camera". Khi người dùng chạm vào lớp phủ này (sự kiện click/tap), camera được khởi tạo thông qua user gesture hợp lệ, giúp kích hoạt hộp thoại xin quyền của iOS và khởi chạy camera thành công.
  - *Đóng giải phóng Camera tức thì*: Khi chuyển đổi giữa các view (hoặc unmount component qua hook `onWillUnmount`), luồng camera được giải phóng triệt để bằng cách gọi `stream.getTracks().forEach(t => t.stop())` và hủy vòng lặp animation frame để tránh xung đột tài nguyên camera ở view mới.
- **UI/UX & Viewport Constraints**: Các component dùng CSS custom trong `barcode_mobile.css` để đảm bảo bố cục co giãn tốt (flex layout), nút bấm to, rõ, phù hợp thao tác bằng một tay. Danh sách sản phẩm cuộn độc lập, đầu trang và chân trang được giữ cố định để tránh tràn màn hình.
- **Thẻ dòng sản phẩm độc lập (Product Cards)**: Mỗi dòng sản phẩm được bao bọc trong một thẻ `.product-row-card` bo tròn 10px, có bóng đổ nhẹ để dễ đọc. Thẻ tự động đổi viền sang màu xanh lá (`border-color: #a5d6a7`) khi quét đủ số lượng.
- **Phản hồi âm thanh & Rung (Audio & Haptic Feedback)**: Khi nhận diện thành công hoặc thất bại, phương thức `playSound()` phát ra tệp âm thanh tương ứng (`success.mp3` hoặc `error.mp3`) kết hợp kích hoạt bộ rung API `navigator.vibrate` trên thiết bị di động để phản hồi vật lý lập tức cho người vận hành (rung 150ms cho thành công, rung kép 2 lần cho lỗi).
- **Triệt tiêu lỗi kẹt cuộn và tràn footer (Absolute & Flex Constraint)**: Do Odoo Web Client có thanh Navbar ở trên cùng, việc sử dụng chiều cao 100vh thông thường sẽ làm lệch và đẩy chân trang (footer) ra ngoài viewport. Ứng dụng giải quyết triệt để lỗi này bằng cách thiết lập `.hlv-barcode-app` định vị tuyệt đối `position: absolute !important` bám khít vào container nội dung `.o_content` của Odoo. Kết hợp với `height: 100% !important` trên `.shipper-container`, mọi flexbox con được khống chế chiều cao nghiêm ngặt. Cho phép danh sách sản phẩm cuộn nội bộ trơn tru, đồng thời ghim chân trang `.picking-footer` và `.subview-footer` cố định ở đáy màn hình.
- **Bố cục 1 cột tối ưu hợp nhất (Unified 1-Column Layout)**: Giữ nguyên giao diện 1 cột đứng thẳng cực kỳ gọn gàng và đồng bộ cho cả Mobile lẫn Desktop. Dải camera nằm ngang được cấu hình cao `160px` trên Mobile.
- **Desktop Camera Expander**: Trên Desktop (màn hình ≥ 992px), camera container tự động mở rộng tối đa `100%` chiều ngang (bám dọc theo container 1200px) và nâng chiều cao lên **`240px`** giúp tăng diện tích quan sát và quét mã cực kỳ trực quan, lấp đầy 2 bên màn hình như yêu cầu.
- **Invisible Keyboard/Scanner Input (Tính năng ẩn)**: Tích hợp một ô input ẩn hoàn toàn nhận tiêu điểm (`focus`) tự động thông qua sự kiện `click` và cơ chế kiểm tra định kỳ (ngoại trừ khi người dùng focus các ô nhập liệu số lượng thực tế khác). Cho phép nhà phát triển hoặc người kiểm thử dán mã vạch (`Ctrl + V`) hoặc quét bằng súng quét USB cầm tay trực tiếp từ bàn phím ở bất kỳ màn hình nào rồi nhấn `Enter` để xử lý và tăng số lượng sản phẩm ngay lập tức (không cần hiển thị ô nhập liệu ra màn hình để tránh người dùng đi tắt dễ sai).
- **Anti-Cheat Copy Blocker (Bảo mật 2 lớp chống đi tắt)**: Ngăn chặn tuyệt đối việc người dùng bôi đen, sao chép mã vạch hiển thị trên giao diện rồi dán (Ctrl+V) để "hoàn thành phiếu khống":
  * *CSS Layer*: Thiết lập `user-select: none !important` trên `.hlv-barcode-app` (ngoại trừ các ô input thực tế có `user-select: text`) để triệt tiêu khả năng bôi đen hay giữ ngón tay lựa chọn văn bản.
  * *JS Event Layer*: Chặn sự kiện sao chép `copy` trên toàn ứng dụng và hiển thị cảnh báo *"Không được phép sao chép thông tin trên trang này!"*.
  * *Context Menu Layer*: Chặn menu chuột phải `contextmenu` trên máy tính tại các vùng tĩnh để ngăn việc kích hoạt menu Copy.
- **Data Sync & Network Fault Tolerance (Chống lệch số lượng do rớt mạng/mạng yếu)**:
  * *Single-Request Processing Lock (isProcessing)*: Khóa hoàn toàn khả năng nhận mã vạch mới hoặc điều hướng khi RPC cũ đang chạy dở dang, tránh Race Condition khi người dùng thao tác quá nhanh lúc mạng chập chờn.
  * *Single-Request Quantity Lock (isProcessingQty)*: Khóa thao tác nút chỉnh nhanh hoặc ô nhập số lượng thủ công trên Picking card trong khi đợi backend phản hồi thành công, ngăn xung đột chèn dữ liệu song song.
  * *F5/Reload vs Exit/Reset Sync*:
    - Khi F5/Reload trang: `localStorage` vẫn lưu giữ `hlv_opened_pickings` giúp số lượng quét hiện tại được giữ nguyên và tải lại an toàn từ backend.
    - Khi Quay lại (`goBack()`), về trang chủ (`goToMain()`), hoặc Làm lại (`clearPicking()`): Xóa `pickingId` khỏi `localStorage` và tự động gửi RPC `/hlv_mobile_barcode/clear_quantities` để reset sạch sẽ toàn bộ dữ liệu quét (hủy và xóa các dòng dịch chuyển/sản phẩm tạo động, reset số lượng đặt trước về 0 và gỡ kiện cho các dòng đặt trước ban đầu), đồng thời làm sạch state vị trí và sản phẩm đã quét ở giao diện.
- **Hierarchical & Sudo Location Stock Lookup (Tra cứu tồn kho phân cấp & Bỏ qua rào cản phân quyền)**:
  * Tối ưu hóa API tra cứu tồn kho vị trí bằng cách thay đổi toán tử tìm kiếm `stock.quant` từ `=` sang `child_of` (`[('location_id', 'child_of', location.id)]`) kết hợp với phương thức `.sudo()`.
  * Việc sử dụng `.sudo()` là bắt buộc để bỏ qua các rào cản phân quyền multi-company hoặc giới hạn vị trí ngầm định của Odoo ORM khi gọi qua RPC, đảm bảo thủ kho luôn thấy 100% dữ liệu tồn kho thực tế.
  * Lọc thêm điều kiện `('quantity', '>', 0.0)` trên cả 3 nhánh tìm kiếm (`product`, `location`, `package`) để tránh hiển thị các dòng quant trống (bản ghi rác).
  * Tích hợp hiển thị nhãn vị trí con cụ thể (`location_name`) bên dưới tên sản phẩm trên giao diện `InventoryLookup` để thủ kho biết chính xác sản phẩm đó đang nằm ở vị trí con cụ thể nào.
- **Sudo Bypass & SKU/Internal Reference Matching (Bypass Quyền hạn & Đồng bộ SKU)**:
  * Áp dụng phương thức `.sudo()` cho toàn bộ các truy vấn `.search()` và `.browse()` liên quan đến Sản phẩm, Vị trí kho, Phiếu kho, và Gói hàng trong tất cả các API đầu cuối của Mobile Barcode để giải quyết triệt để lỗi "Không tìm thấy" do multi-company hoặc record rules của Odoo ORM chặn ngầm.
  * Quét sản phẩm trong `smart_scan` và `process_barcode` hỗ trợ khớp đồng thời cả trường **Mã vạch (`barcode`)** lẫn **Mã SKU/Tham chiếu nội bộ (`default_code`)** của sản phẩm.
  * Quét/Dán vị trí trong `smart_scan` hỗ trợ khớp cả **Mã vạch vị trí (`barcode`)** lẫn **Tên vị trí (`name`)**.
  * Quét hoặc tra cứu Kiện hàng/Gói hàng (`stock.quant.package`) tự động phân tích vị trí hiện tại của gói hoặc các `stock.quant` chứa bên trong để truy xuất đúng mã kho thực tế (`warehouse_code`), cập nhật tiêu đề Header thay vì hiển thị "Kho HLV" tĩnh.
  * Tự động cắt bỏ các khoảng trắng thừa (`.strip()`) ở hai đầu chuỗi quét ở tất cả các router backend, ngăn lỗi do máy quét cầm tay tự động nối thêm phím Enter/Tab.
- **Dynamic Warehouse Header**: API tự động trả về `warehouse_code` thực tế của phiếu kho (`picking.picking_type_id.warehouse_id.code` hoặc `location.warehouse_id.code`), hiển thị động lên Header dạng "Kho KBC", "Kho TSN"... thay vì "Kho HLV" tĩnh.
- **Liên kết & Chuyển đổi trực tiếp Quy trình 2 bước (INT -> IN / STOR)**:
  - Khi hoàn thành hoặc quét một phiếu chuyển kho Bước 1 (`INT` - Internal Transfer) có trạng thái `done` (hoàn tất), ứng dụng hiển thị chi tiết thông tin phiếu và cung cấp một nút bấm nổi bật **"Chuyển sang Bước 2 (<Tên phiếu bước 2>)"** ngay phía trên chân trang.
  - *Cơ chế tìm kiếm liên kết*: Backend tự động tìm kiếm phiếu Bước 2 (`IN` hoặc `STOR`) thông qua 4 phương pháp ưu tiên (gọn gàng, tin cậy):
    1. **Tin nhắn Chatter (Chatter Message - Ưu tiên cao nhất)**: Khi Odoo tạo phiếu Bước 2 từ phiếu Bước 1 thông qua push rules, hệ thống sẽ tự động đăng tin nhắn trong Chatter (ví dụ: "This transfer has been created from: KBC/INT/02042"). Backend tìm kiếm trong `mail.message` với `model='stock.picking'` và `body` chứa tên của phiếu Bước 1 để lấy ID phiếu mới.
    2. **Chuỗi dịch chuyển (Stock Moves Chain)**: Sử dụng quan hệ `move_dest_ids.picking_id` để tìm các stock.picking đích hợp lệ (Odoo native chain).
    3. **Nhóm cung ứng (Procurement Group)**: Tìm kiếm các stock.picking khác có cùng `group_id` và có mã sequence chứa ký tự `'IN'` hoặc `'STOR'` hoặc thuộc loại `incoming`/`internal`.
    4. **Nguồn gốc tài liệu (Origin)**: Tìm kiếm các phiếu có trường `origin` khớp chính xác hoặc chứa tên của phiếu Bước 1.
  - Khi người dùng nhấp nút chuyển đổi, ứng dụng thực hiện giải phóng camera cũ, lưu lịch sử duyệt (`pushHistory()`), cập nhật trạng thái mục tiêu và kích hoạt lại camera trên phiếu Bước 2 mới một cách mượt mà không bị lỗi gắn kết DOM.

- **Chế độ Chuyển kho Đa vị trí (Multi-Location Batch Move)**:
  - Cho phép người dùng chuyển sản phẩm từ nhiều kệ hàng (vị trí con) khác nhau vào một phiếu kho chung (ví dụ dọn kho, gom hàng).
  - Về mặt Logic Odoo: Lệnh chuyển (INT) được tạo có `location_id` là kho lưu trữ chung (`lot_stock_id` của Warehouse) để bao hàm toàn bộ. Tuy nhiên các dòng `stock.move.line` sẽ được ép cứng mã vị trí nguồn `ml_src_id` trỏ thẳng vào từng vị trí con (Kệ hàng) cụ thể mà người dùng quét.
  - Về mặt UI/UX: Ứng dụng yêu cầu và ép buộc người dùng phải quét mã Vị trí (Kệ hàng) trước để xác nhận "điểm lấy hàng" hiện tại. Sau đó mọi sản phẩm được quét đều sẽ thuộc về vị trí này cho đến khi người dùng quét mã vị trí khác để đổi kệ.

## API / Controllers
- `/hlv_mobile_barcode/smart_scan`: Đầu vào `barcode`. Trả về đối tượng khớp đầu tiên theo thứ tự ưu tiên: Picking > Product > Location > Package, đồng thời trả kèm thêm trường `warehouse_code`.
- `/hlv_mobile_barcode/get_picking_data`: Trả về JSON tree chi tiết các dòng dịch chuyển (stock.move.line) của một Picking để hiển thị riêng biệt theo kiện (Package) hoặc hàng lẻ (Unpacked), bao gồm cả `warehouse_code`, các thông tin liên kết 2 bước `linked_picking_id`, `linked_picking_name` và danh sách tóm tắt kiện hàng (`packages`).
  - *Lọc vị trí PICK*: Đối với phiếu PICK (tên/code chứa "PICK"), backend chỉ trả về các dòng dịch chuyển đã có vị trí nguồn (move_line_ids tồn tại). Các dòng chưa phân bổ vị trí sẽ bị bỏ qua. Nếu không có dòng nào hợp lệ, trả về lỗi yêu cầu chờ hệ thống phân bổ xong.
- `/hlv_mobile_barcode/process_barcode`: Cập nhật `quantity` khi quét sản phẩm, vị trí, hoặc kiện hàng. Hỗ trợ bỏ qua và tự tạo dòng mới khi quét sản phẩm đã được đóng gói/nằm trong kiện hàng, tránh ghi đè số lượng đã đóng gói.
  * *Giải quyết vị trí con (Child Location Resolution)*: Khi quét từ vị trí cha (ví dụ A1-T1) nhưng tồn kho thực tế nằm ở vị trí con (A1-T1/THUNG 1), hệ thống tự động tìm và gán đúng vị trí con có hàng vào `location_id` của move line, đảm bảo Odoo validate picking thành công.
  * *Giới hạn số lượng quét theo tồn kho thực tế*: Kiểm tra tổng số lượng đã quét cho cùng sản phẩm trên TOÀN BỘ picking (không chỉ 1 move) tại cây vị trí nguồn (bao gồm tất cả vị trí con). Nếu vượt quá tồn kho thực tế → chặn quét và thông báo lỗi rõ ràng.
  * *Hỗ trợ quét Kiện hàng (Package)*: Được kiểm soát thông qua cấu hình **"Cho phép quét Kiện hàng" (hlv_barcode_allow_package_scan)** trong Cài đặt hệ thống (mặc định bật). Khi người dùng quét mã vạch của kiện hàng (`stock.quant.package`):
    1. Kiểm tra xem phiếu kho có dòng dịch chuyển (move line) nào dành riêng cho kiện hàng này không (khớp `package_id` hoặc `result_package_id`). Nếu có, tự động cập nhật số lượng hoàn tất cho các dòng đó theo số lượng reserved.
    2. Nếu không có dòng dịch chuyển riêng cho kiện hàng, hệ thống tự động tra cứu danh sách sản phẩm và số lượng thực tế chứa trong kiện thông qua `stock.quant`, sau đó tự động khớp, bổ sung và cập nhật số lượng hoàn thành tương ứng cho các sản phẩm đó trong phiếu một cách hàng loạt.
- `/hlv_mobile_barcode/put_in_pack`: Đóng gói các dòng có số lượng đã quét lẻ thành Package. Trả về tên kiện hàng vừa đóng gói (`package_name`) và cờ `print_after_pack`.
- `/hlv_mobile_barcode/unpack_move_line`: Gỡ sản phẩm ra khỏi kiện hàng (xóa `package_id` và `result_package_id` trên dòng dịch chuyển được chọn) để chuyển về dạng hàng lẻ, cho phép chỉnh sửa hoặc quét bổ sung.
- `/hlv_mobile_barcode/get_package_details`: Trả về chi tiết các sản phẩm trong kiện hiện tại, các kiện khác có thể chuyển sang, và danh sách sản phẩm lẻ chưa đóng gói để thêm vào kiện.
- `/hlv_mobile_barcode/update_package_item_qty`: Điều chỉnh số lượng sản phẩm trong kiện. Nếu giảm, tách phần thừa ra thành hàng lẻ (không mất số lượng đã quét).
- `/hlv_mobile_barcode/remove_package_item`: Gỡ sản phẩm khỏi kiện, trả về dạng hàng lẻ đã quét (unpack).
- `/hlv_mobile_barcode/add_item_to_package`: Thêm số lượng sản phẩm lẻ (đã quét) vào kiện hiện tại.
- `/hlv_mobile_barcode/transfer_item_between_packages`: Di chuyển số lượng sản phẩm từ kiện này sang kiện khác một cách trực tiếp.
- `/hlv_mobile_barcode/get_inventory_lookup`: Truy vấn `stock.quant` cho màn hình tra cứu, tự động xác định `warehouse_code` từ vị trí kho.
- `/hlv_mobile_barcode/move_location`: Tạo lệnh `stock.picking` type Internal và xử lý tự động validate để di chuyển tồn kho.

## Quản lý Kiện hàng nâng cao (Package Management Section & Edit Modal)
Ứng dụng Mobile Barcode phân tách hoàn toàn hiển thị kiện hàng thành một khu vực riêng và bổ sung modal chỉnh sửa chi tiết:
- **Khu vực Kiện hàng (Collapsible Packages Section)**:
  - Hiển thị ngay trên danh sách sản phẩm, tự động thu gọn/mở rộng.
  - Các kiện hàng được hiển thị dưới dạng Card trực quan, tóm tắt các sản phẩm chứa bên trong và hiển thị nút "Chỉnh sửa" để quản lý.
- **Modal Chỉnh sửa Kiện hàng (Package Edit Modal)**:
  - Modal toàn màn hình tối ưu cho Mobile Web, hiển thị danh sách sản phẩm trong kiện.
  - Cho phép điều chỉnh trực tiếp số lượng (+/- 1) của từng dòng trong kiện (tự động cập nhật qua endpoint `update_package_item_qty`).
  - Gỡ sản phẩm khỏi kiện về dạng hàng lẻ (qua endpoint `remove_package_item`).
  - Thêm sản phẩm lẻ (đã quét trước đó) vào kiện trực tiếp từ danh sách chọn (qua endpoint `add_item_to_package`).
  - Chuyển đổi số lượng sản phẩm trực tiếp từ kiện hiện tại sang một kiện đích khác trong cùng phiếu (qua endpoint `transfer_item_between_packages`).


## Phân quyền quét Barcode di động (Hệ thống Nút gạt Động)
Để tăng tính tự động hóa và bảo mật tối đa, ứng dụng Mobile Barcode tích hợp hệ thống phân quyền quét kho động, cho phép linh hoạt cấu hình và chuyển đổi:
* **Models**:
  - `hlv.barcode.user.permission`: Định cấu hình người dùng (`res.users`) tại từng kho (`stock.warehouse`).
  - `hlv.barcode.picking.permission`: Cấu hình quyền chi tiết cho từng loại phiếu quét (`IN`, `OUT`, `INT`, `PICK`, `PACK`, `STO`) với các cờ boolean: `can_view` (Xem/Quét), `can_edit` (Sửa/Quét hàng), `can_delete` (Xóa dòng), `can_confirm` (Xác nhận phiếu).
* **Nút gạt cấu hình (Toggle Setting)**:
  - Tham số `hlv_barcode_use_independent_permissions` trong `ir.config_parameter` (được cấu hình qua Settings) cho phép quản trị viên lựa chọn:
    - **Bật (True)**: Sử dụng cấu hình phân quyền quét của riêng Mobile Barcode (`hlv.barcode.*`).
    - **Tắt (False - Mặc định)**: Dùng chung cấu hình phân quyền kho của module `hlv_warehouse_permission` (`warehouse.*`).
* **Tránh lỗi biên dịch XML (Resilient Runtime Routing)**:
  - Để tránh lỗi `ParseError` khi cài đặt module trên hệ thống không có `hlv_warehouse_permission`:
    - Giao diện cài đặt sử dụng **nút gọi Python object (`action_open_warehouse_permissions`)** thay vì dùng action ID tĩnh để mở trang cấu hình chung của `hlv_warehouse_permission`.
    - Menu phụ debug *"Phân quyền quét kho"* gọi một **Odoo Server Action (`action_open_barcode_permissions_menu`)**, tự động kiểm tra trạng thái nút gạt để trả về trang cấu hình tương ứng ở runtime.
* **Kiểm tra quyền đa hình (Polymorphic Validation)**:
  - Cả 6 API controllers kiểm tra quyền (`smart_scan`, `get_picking_data`, `process_barcode`, `update_move_line_qty`, `delete_move`, `validate_picking`) tự động quyết định model cần truy vấn tại runtime dựa trên nút gạt.
  - Nếu module đích chưa cài đặt, `request.env.get(...)` sẽ trả về `None` một cách an toàn mà không bao giờ gây crash hệ thống.

## Hướng dẫn mở rộng
- Khi cần thêm loại mã vạch mới: Thêm logic tìm kiếm vào endpoint `smart_scan` ở `controllers/main.py`.
- Khi cần thêm tính năng xử lý, có thể tạo thêm các component OWL trong `static/src/components` và import vào `barcode_app.js`.
- Bố cục 1 cột được thiết lập thống nhất nên giao diện di động và desktop sẽ đồng nhất 100%, bảo trì đơn giản mà không sợ phát sinh lỗi hiển thị chéo nền tảng.
