# TECHNICAL.md - Milwaukee Website Embedded

## Mục đích module
Nhúng toàn bộ website Milwaukee (Next.js) vào Odoo thông qua giao diện Iframe tích hợp. Hỗ trợ hiển thị dashboard Admin, quản lý sản phẩm, đơn hàng, và trang khách hàng ngay trong giao diện Odoo.

## Cấu trúc thư mục
```
hlv_milwaukee_embedded/
├── models/
│   └── res_config_settings.py     ← Quản lý biến môi trường (Base URL)
├── static/
│   └── src/
│       ├── js/
│       │   └── milwaukee_iframe.js   ← OWL 2.0 Component (Action) render Iframe
│       └── xml/
│           └── milwaukee_iframe.xml  ← Giao diện Iframe
└── views/
    ├── milwaukee_menus.xml          ← Menu điều hướng gọi OWL Action
    └── res_config_settings_views.xml ← UI Cài đặt cấu hình Base URL
```

## Luồng xử lý chính
1. Người dùng truy cập Menu "Milwaukee" trong Odoo.
2. Menu kích hoạt `ir.actions.client` với tag `milwaukee_iframe_action` và chứa biến `{ 'iframe_path': '/...'}` trong context.
3. Component `MilwaukeeIframeAction` (JS/OWL) được khởi chạy.
4. Nó đọc tham số `milwaukee.base_url` từ `ir.config_parameter` thông qua ORM Service.
5. Component gắn đường dẫn truy cập (vd: `/admin/products?embedded=1`) với Base URL để cho ra Iframe Source đầy đủ.
6. Component render Template XML chứa thẻ `<iframe>` tự động lấp đầy giao diện màn hình để hiển thị Website Next.js.

## Quyền & Bảo mật
Next.js server phải cấu hình `Content-Security-Policy: frame-ancestors *;` hoặc trỏ domain về server Odoo. Đồng thời Next.js quản lý phiên đăng nhập và Cookie cục bộ khi người dùng Odoo tương tác với form login bên trong Iframe.

## Hướng dẫn mở rộng
- **Thêm Menu trang mới**: Truy cập `views/milwaukee_menus.xml`, định nghĩa một `ir.actions.client` với `iframe_path` tương ứng và liên kết đến một menu item. Không cần viết thêm Python hoặc JS.
- **Tuỳ chỉnh CSS Iframe**: Can thiệp bằng cách sửa `static/src/xml/milwaukee_iframe.xml`. 
