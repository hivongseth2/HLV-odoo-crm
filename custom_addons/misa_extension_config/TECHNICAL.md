# MISA Extension Config (`misa_extension_config`)

## Mục đích
Module master config cho Chrome/Browser Extension MISA → Odoo. 
Cung cấp API `/api/extension/config` để Extension tự động fetch cấu hình động (nút, badge, status field, grid column, styles, API endpoints, positioning) mà không cần thay đổi source code của Extension.

## Cấu trúc thư mục
```
misa_extension_config/
├── controllers/             ← Controller layer
│   ├── __init__.py
│   └── main.py              ← Endpoint GET /api/extension/config (public / CORS)
├── data/                    ← Initial data
│   └── seed_elements.xml    ← Config seed mặc định cho Purchase Order & Purchase Request
├── models/                  ← Models layer
│   ├── __init__.py
│   ├── misa_extension_config_version.py  ← Quản lý phiên bản config & min extension version
│   └── misa_extension_element.py         ← Chi tiết từng UI element (button, badge, column...)
├── security/
│   └── ir.model.access.csv  ← Phân quyền truy cập cho models
├── views/
│   └── misa_extension_config_views.xml   ← Giao diện Odoo (List/Form views & Menus)
├── TECHNICAL.md             ← Tài liệu kỹ thuật
├── __init__.py
└── __manifest__.py
```

## Các Models chính
1. `misa.extension.config.version`: Quản lý phiên bản cấu hình (`version`, `min_extension_version`, `published_at`, `notes`).
2. `misa.extension.element`: Quản lý từng element UI (`code`, `name`, `element_type`, `page_type`, `anchor_selector`, `anchor_strategy`, `handler_key`, `endpoint`, `styles`, `state_config`, `column_config`, `requires_data_event`, `auto_trigger_event`).

## Endpoints
- `GET /api/extension/config`: Trả về toàn bộ danh sách active elements và thông tin phiên bản mới nhất cho Extension.

## Quy tắc tương thích Odoo 18
- Sử dụng `<list>` view thay cho `<tree>` view trong tất cả XML view definition.
- `view_mode` dùng `list,form`.
