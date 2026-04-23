# Milwaukee Pricing Sync (HLV)

Module đồng bộ giá từ Odoo sang website Milwaukee thông qua REST API.

## Mục đích
- Quản lý giá tập trung tại Odoo.
- Đồng bộ `regularPrice` và `salePrice` sang Website dựa trên SKU.
- Hỗ trợ đồng bộ hàng loạt (Wizard) hoặc đồng bộ nhanh từng sản phẩm.

## Cấu trúc thư mục
```
hlv_milwaukee_price_sync/
├── models/
│   ├── product_template.py      # Thêm các field milwaukee_id và các action sync
│   └── res_config_settings.py   # Cấu hình API URL và API Key
├── wizard/
│   └── milwaukee_price_sync_wizard.py  # Wizard đồng bộ hàng loạt sản phẩm được chọn
├── views/
│   ├── milwaukee_pricing_views.xml      # View quản lý giá tập trung (list editable)
│   ├── milwaukee_price_sync_wizard_views.xml
│   ├── product_template_views.xml
│   └── res_config_settings_views.xml
├── security/
│   └── ir.model.access.csv
└── TECHNICAL.md
```

## Luồng xử lý chính
1. **Cấu hình**: User vào Inventory > Configuration > Settings để thiết lập URL API của Milwaukee.
2. **Mapping sản phẩm**: 
   - Nhấn "Đồng bộ Sản Phẩm Về" để fetch toàn bộ SKU từ Website.
   - Odoo tìm sản phẩm khớp theo `default_code`.
   - Nếu khớp, lưu `milwaukee_id` từ Web vào Odoo.
3. **Đồng bộ giá**:
   - Tại view "Quản lý giá Milwaukee", user chỉnh sửa `x_studio_ga_hng_nim_yt` (Regular) và `x_studio_gi_web` (Sale).
   - Nhấn "Đồng bộ" (individual) hoặc chọn nhiều SP -> Action "Đồng bộ giá Milwaukee".
   - Odoo gọi API `PUT /api/products/sync-price` (ví dụ) gửi `milwaukee_id` và giá mới.

## Nguyên tắc kỹ thuật
- **DRY**: Logic gọi API được đặt trong `res_config_settings.py` (hoặc method dùng chung) để tái sử dụng.
- **Odoo 18**: Sử dụng tag `<list>` thay cho `<tree>`.
- **Fields**:
  - `x_studio_ga_hng_nim_yt`: regularPrice
  - `x_studio_gi_web`: salePrice
