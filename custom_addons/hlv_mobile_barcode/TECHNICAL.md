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
- **Persistent Inline Camera**: Camera được nhúng trực tiếp ở phần trên cùng của ứng dụng để quét liên tục. Sau mỗi lần quét thành công, camera tạm dừng 1.5 giây để xử lý rồi tự động kích hoạt lại.
- **Xử lý Quyền & Bảo mật Camera di động**:
  - *HTTPS Context*: Kiểm tra `window.isSecureContext`. Nếu truy cập qua HTTP (không bảo mật), hệ thống tự động tắt camera trực tiếp và hiển thị thông báo yêu cầu HTTPS, đồng thời kích hoạt fallback (chụp ảnh bằng file input).
  - *iOS / Safari / Chrome User Gesture*: Để tránh việc hệ thống iOS (WKWebView) tự động từ chối (`NotAllowedError`) khi gọi camera tự động lúc tải trang (`onMounted`), component sẽ hiển thị một lớp phủ "Kích hoạt Camera". Khi người dùng chạm vào lớp phủ này (sự kiện click/tap), camera được khởi tạo thông qua user gesture hợp lệ, giúp kích hoạt hộp thoại xin quyền của iOS và khởi chạy camera thành công.
- **UI/UX & Viewport Constraints**: Các component dùng CSS custom trong `barcode_mobile.css` để đảm bảo bố cục co giãn tốt (flex layout), nút bấm to, rõ, phù hợp thao tác bằng một tay. Danh sách sản phẩm cuộn độc lập, đầu trang và chân trang được giữ cố định để tránh tràn màn hình.
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
    - Khi Quay lại (`goBack()`), về trang chủ (`goToMain()`), hoặc Làm lại (`clearPicking()`): Xóa `pickingId` khỏi `localStorage` và tự động gửi RPC `/hlv_mobile_barcode/clear_quantities` để reset sạch sẽ số lượng quét về 0 trên backend, đảm bảo tính nhất quán của cơ sở dữ liệu.
- **Hierarchical & Sudo Location Stock Lookup (Tra cứu tồn kho phân cấp & Bỏ qua rào cản phân quyền)**:
  * Tối ưu hóa API tra cứu tồn kho vị trí bằng cách thay đổi toán tử tìm kiếm `stock.quant` từ `=` sang `child_of` (`[('location_id', 'child_of', location.id)]`) kết hợp với phương thức `.sudo()`.
  * Việc sử dụng `.sudo()` là bắt buộc để bỏ qua các rào cản phân quyền multi-company hoặc giới hạn vị trí ngầm định của Odoo ORM khi gọi qua RPC, đảm bảo thủ kho luôn thấy 100% dữ liệu tồn kho thực tế.
  * Lọc thêm điều kiện `('quantity', '>', 0.0)` trên cả 3 nhánh tìm kiếm (`product`, `location`, `package`) để tránh hiển thị các dòng quant trống (bản ghi rác).
  * Tích hợp hiển thị nhãn vị trí con cụ thể (`location_name`) bên dưới tên sản phẩm trên giao diện `InventoryLookup` để thủ kho biết chính xác sản phẩm đó đang nằm ở vị trí con cụ thể nào.
- **Sudo Bypass & SKU/Internal Reference Matching (Bypass Quyền hạn & Đồng bộ SKU)**:
  * Áp dụng phương thức `.sudo()` cho toàn bộ các truy vấn `.search()` và `.browse()` liên quan đến Sản phẩm, Vị trí kho, Phiếu kho, và Gói hàng trong tất cả các API đầu cuối của Mobile Barcode để giải quyết triệt để lỗi "Không tìm thấy" do multi-company hoặc record rules của Odoo ORM chặn ngầm.
  * Quét sản phẩm trong `smart_scan` và `process_barcode` hỗ trợ khớp đồng thời cả trường **Mã vạch (`barcode`)** lẫn **Mã SKU/Tham chiếu nội bộ (`default_code`)** của sản phẩm.
  * Quét/Dán vị trí trong `smart_scan` hỗ trợ khớp cả **Mã vạch vị trí (`barcode`)** lẫn **Tên vị trí (`name`)**.
  * Tự động cắt bỏ các khoảng trắng thừa (`.strip()`) ở hai đầu chuỗi quét ở tất cả các router backend, ngăn lỗi do máy quét cầm tay tự động nối thêm phím Enter/Tab.
- **Dynamic Warehouse Header**: API tự động trả về `warehouse_code` thực tế của phiếu kho (`picking.picking_type_id.warehouse_id.code` hoặc `location.warehouse_id.code`), hiển thị động lên Header dạng "Kho KBC", "Kho TSN"... thay vì "Kho HLV" tĩnh.

## API / Controllers
- `/hlv_mobile_barcode/smart_scan`: Đầu vào `barcode`. Trả về đối tượng khớp đầu tiên theo thứ tự ưu tiên: Picking > Product > Location > Package, đồng thời trả kèm thêm trường `warehouse_code`.
- `/hlv_mobile_barcode/get_picking_data`: Trả về JSON tree chi tiết các line của một Picking để hiển thị, bao gồm cả `warehouse_code`.
- `/hlv_mobile_barcode/process_barcode`: Cập nhật `qty_done` khi quét sản phẩm nằm trong picking.
- `/hlv_mobile_barcode/put_in_pack`: Đóng gói các dòng `qty_done` > 0 thành Package. Hỗ trợ trả cờ `print_after_pack` theo cấu hình.
- `/hlv_mobile_barcode/get_inventory_lookup`: Truy vấn `stock.quant` cho màn hình tra cứu, tự động xác định `warehouse_code` từ vị trí kho.
- `/hlv_mobile_barcode/move_location`: Tạo lệnh `stock.picking` type Internal và xử lý tự động validate để di chuyển tồn kho.

## Hướng dẫn mở rộng
- Khi cần thêm loại mã vạch mới: Thêm logic tìm kiếm vào endpoint `smart_scan` ở `controllers/main.py`.
- Khi cần thêm tính năng xử lý, có thể tạo thêm các component OWL trong `static/src/components` và import vào `barcode_app.js`.
- Bố cục 1 cột được thiết lập thống nhất nên giao diện di động và desktop sẽ đồng nhất 100%, bảo trì đơn giản mà không sợ phát sinh lỗi hiển thị chéo nền tảng.
