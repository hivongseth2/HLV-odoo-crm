# TECHNICAL.md - Milwaukee Website Integration (Master sync)

## Mục đích module
Quản lý nội dung website Milwaukee (Next.js) trực tiếp từ giao diện Odoo. Module này đã chuyển đổi từ việc nhúng Iframe sang sử dụng **Native Odoo Models** để đồng bộ dữ liệu qua **Master API**.

## Cấu trúc thư mục
```
hlv_milwaukee_embedded/
├── models/
│   ├── milwaukee_master_mixin.py  ← Logic dùng chung để gọi Master API (POST /entity)
│   ├── product_template.py        ← Kế thừa Product để sync Sản phẩm
│   ├── milwaukee_banner.py        ← Model quản lý Banner Website
│   ├── milwaukee_blog_post.py     ← Model quản lý Bài viết Website
│   └── res_config_settings.py     ← Cài đặt Base URL và Master API Key
├── views/
│   ├── milwaukee_master_views.xml  ← Native Form/List views cho Banner, Blog, Product
│   ├── milwaukee_menus.xml         ← Menu điều hướng (Native Actions)
│   └── res_config_settings_views.xml
├── security/
│   └── ir.model.access.csv         ← Phân quyền cho các model mới
└── static/                         ← (Legacy) Chứa Iframe components cho Live Preview
```

## Luồng xử lý chính (Native Sync)
1. **Source of Truth**: Odoo là nơi nhập liệu chính cho Sản phẩm, Banner và Bài viết.
2. **Auto-Sync**: Khi một bản ghi được tạo mới hoặc cập nhật (method `create`/`write`), Odoo tự động chuẩn bị JSON và gửi `POST` request đến `[Base URL]/api/v1/master/[entity]`.
3. **Master API**: Server Next.js nhận dữ liệu, thực hiện `upsert` (cập nhật nếu trùng SKU/ID, nếu không thì tạo mới) và trả về `milwaukee_id`.
4. **Tracking**: Odoo lưu lại `milwaukee_id` và `last_sync_date` để quản lý trạng thái đồng bộ.

## Master API Details
- **Headers**: `x-api-key` (lấy từ Settings).
- **Entities hỗ trợ**: `products`, `banners`, `blog_posts`.
- **Phòng ngừa vòng lặp**: Sử dụng context `milwaukee_sync_done` khi cập nhật `milwaukee_id` từ kết quả API.

## Hướng dẫn mở rộng
- **Thêm thực thể mới**: 
    1. Tạo model kế thừa `milwaukee.master.mixin`.
    2. Override method `_sync_to_milwaukee` để map fields sang JSON.
    3. Thêm menu và view tương ứng.
- **Xem trực tiếp**: Sử dụng Action `milwaukee_iframe_action` với context `iframe_path` để xem kết quả hiển thị trên Website Web qua Iframe.
