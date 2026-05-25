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

## API / Controllers
- `/hlv_mobile_barcode/smart_scan`: Đầu vào `barcode`. Trả về đối tượng khớp đầu tiên theo thứ tự ưu tiên: Picking > Product > Location > Package.
- `/hlv_mobile_barcode/get_picking_data`: Trả về JSON tree chi tiết các line của một Picking để hiển thị.
- `/hlv_mobile_barcode/process_barcode`: Cập nhật `qty_done` khi quét sản phẩm nằm trong picking.
- `/hlv_mobile_barcode/put_in_pack`: Đóng gói các dòng `qty_done` > 0 thành Package. Hỗ trợ trả cờ `print_after_pack` theo cấu hình.
- `/hlv_mobile_barcode/get_inventory_lookup`: Truy vấn `stock.quant` cho màn hình tra cứu.
- `/hlv_mobile_barcode/move_location`: Tạo lệnh `stock.picking` type Internal và xử lý tự động validate để di chuyển tồn kho.

## Hướng dẫn mở rộng
- Khi cần thêm loại mã vạch mới: Thêm logic tìm kiếm vào endpoint `smart_scan` ở `controllers/main.py`.
- Khi cần thêm tính năng xử lý, có thể tạo thêm các component OWL trong `static/src/components` và import vào `barcode_app.js`.
