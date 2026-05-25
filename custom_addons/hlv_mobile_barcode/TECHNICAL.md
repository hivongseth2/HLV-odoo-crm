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
- UI/UX: Các component dùng CSS custom trong `barcode_mobile.css` để đảm bảo bố cục co giãn tốt (flex layout), nút bấm to, rõ, phù hợp thao tác bằng một tay. Danh sách sản phẩm cuộn độc lập, đầu trang và chân trang được giữ cố định để tránh tràn màn hình.
- **Triệt tiêu lỗi kẹt cuộn và tràn footer (Absolute & Flex Constraint)**: Do Odoo Web Client có thanh Navbar ở trên cùng, việc sử dụng chiều cao 100vh thông thường sẽ làm lệch và đẩy chân trang (footer) ra ngoài viewport. Ứng dụng giải quyết triệt để lỗi này bằng cách thiết lập `.hlv-barcode-app` định vị tuyệt đối `position: absolute !important` bám khít vào container nội dung `.o_content` của Odoo. Kết hợp với `height: 100% !important` trên `.shipper-container`, mọi flexbox con được khống chế chiều cao nghiêm ngặt. Cho phép danh sách sản phẩm cuộn nội bộ trơn tru, đồng thời ghim chân trang `.picking-footer` và `.subview-footer` cố định ở đáy màn hình.
- **Bố cục 1 cột tối ưu hợp nhất (Unified 1-Column Layout)**: Giữ nguyên giao diện 1 cột đứng thẳng cực kỳ gọn gàng và đồng bộ cho cả Mobile lẫn Desktop. Dải camera nằm ngang được cấu hình cao `160px` trên Mobile.
- **Desktop Camera Expander**: Trên Desktop (màn hình ≥ 992px), camera container tự động mở rộng tối đa `100%` chiều ngang (bám dọc theo container 1200px) và nâng chiều cao lên **`240px`** giúp tăng diện tích quan sát và quét mã cực kỳ trực quan, lấp đầy 2 bên màn hình như yêu cầu.
- **Invisible Keyboard/Scanner Input (Tính năng ẩn)**: Tích hợp một ô input ẩn hoàn toàn nhận tiêu điểm (`focus`) tự động thông qua sự kiện `click` và cơ chế kiểm tra định kỳ (ngoại trừ khi người dùng focus các ô nhập liệu số lượng thực tế khác). Cho phép nhà phát triển hoặc người kiểm thử dán mã vạch (`Ctrl + V`) hoặc quét bằng súng quét USB cầm tay trực tiếp từ bàn phím ở bất kỳ màn hình nào rồi nhấn `Enter` để xử lý và tăng số lượng sản phẩm ngay lập tức (không cần hiển thị ô nhập liệu ra màn hình để tránh người dùng đi tắt dễ sai).
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
