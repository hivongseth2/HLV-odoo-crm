# Tài liệu kỹ thuật module `hlv_zalo_miniapp_api`

## Mục đích

Module cung cấp REST API cho Zalo Mini App đồng thời đóng vai trò là **Ứng dụng quản trị (Main Application)** trung tâm trên Odoo Backend giúp người dùng quản lý, lọc và cấu hình dữ liệu Zalo Mini App (Banners, Sản phẩm, Danh mục, Khách hàng, Đơn hàng).

## Cấu trúc thư mục

```
hlv_zalo_miniapp_api/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── banner.py               # Model zalo.miniapp.banner (quản lý banner)
│   ├── product_product.py      # Mở rộng product.product: x_zalo_price, x_active_zalo
│   ├── res_partner.py           # Mở rộng res.partner: x_is_zalo_account
│   └── loyalty_portal_account.py# Mở rộng hlv.loyalty.portal.account cho partner_id domain
├── controllers/
│   ├── __init__.py
│   ├── banner_api.py            # API banner (/api/v1/zalo/banners/*)
│   ├── category_api.py          # API danh mục (pos.category)
│   ├── product_api.py           # API sản phẩm (product.product variant)
│   ├── contact_api.py           # API contact (auth, CRUD, addresses)
│   ├── cart_api.py              # API giỏ hàng (sale.order draft)
│   └── order_api.py             # API đơn hàng (list/detail/create/cancel)
├── views/
│   ├── menu_views.xml          # Menu chính & phân cấp cho Zalo Mini App
│   ├── banner_views.xml        # View cho Banners
│   ├── product_product_views.xml # Views & Action filter sản phẩm Zalo
│   ├── product_template_views.xml# Views bổ sung fields Zalo trên template
│   ├── res_partner_views.xml   # Views & Action filter khách hàng Zalo
│   ├── sale_order_views.xml    # Custom List View (view_order_zalo_tree) & Action filter đơn hàng Zalo Mini App
│   └── zalo_loyalty_portal_account_views.xml # Form, List, Search views & Action quản lý Tài khoản Portal Zalo Mini App (Khách hàng cá nhân)
├── security/
│   └── ir.model.access.csv
└── TECHNICAL.md
```

## Phụ thuộc

- `sale_management` - sale.order cho giỏ hàng và đơn hàng
- `stock` - stock.quant cho tồn kho
- `contacts` - res.partner cho contact
- `hlv_loyalty` - hlv.loyalty.portal.account cho auth, hlv.loyalty.voucher cho voucher
- `point_of_sale` - pos.category cho danh mục

## Quy tắc kiến trúc

1. **Controllers layer** - Xử lý HTTP request/response, gọi `sudo()` để bypass security
2. **Models layer** - Chỉ mở rộng field, không chứa business logic phức tạp
3. **Auth** - Dùng token HMAC với `Authorization: Bearer <token>` header. Dev mode dùng secret mặc định
4. **Tất cả API list** đều nhận `limit` và `offset` để phân trang

## Models

### `product.product` (kế thừa)

| Field | Type | Mô tả |
|---|---|---|
| `x_zalo_price` | Float | Giá hiển thị trên Zalo Mini App |
| `x_active_zalo` | Boolean | Chỉ sản phẩm có flag = True mới xuất hiện |
| `x_zalo_categ_ids` | Many2many (pos.category) | Danh mục Zalo riêng, kế thừa từ POS category. Không phụ thuộc `available_in_pos` |

### `pos.category` (kế thừa)

| Field | Type | Mô tả |
|---|---|---|
| `x_active_zalo` | Boolean | Hiển thị trên Zalo Mini App (default: True). Lọc ẩn/hiện danh mục trên API |
| `x_is_featured_zalo` | Boolean | Danh mục nổi bật Zalo Mini App |

### `res.partner` (kế thừa)

| Field | Type | Mô tả |
|---|---|---|
| `x_is_zalo_account` | Boolean | Đánh dấu contact đã đăng ký Zalo |

### `zalo.miniapp.banner` (mới)

| Field | Type | Mô tả |
|---|---|---|
| `name` | Char | Tên Banner (bắt buộc) |
| `active` | Boolean | Trạng thái kích hoạt (default: True) |
| `sequence` | Integer | Thứ tự hiển thị (default: 10) |
| `image` | Image | Hình ảnh banner (base64) |
| `link` | Char | Link khi click vào banner |

### `zalo.miniapp.cart.line` (mới)

| Field | Type | Mô tả |
|---|---|---|
| `partner_id` | Many2one (res.partner) | Khách hàng Zalo sở hữu giỏ hàng |
| `product_id` | Many2one (product.product) | Sản phẩm chọn mua |
| `quantity` | Float | Số lượng sản phẩm |
| `price_unit` | Float | Đơn giá hiển thị (tính từ `x_zalo_price` / `list_price`) |

## API Endpoints

### Banner API - `/api/v1/zalo/banners/*`

| Method | Route | Mô tả |
|---|---|---|
| POST | `/api/v1/zalo/banners/list` | Danh sách banner (chỉ lấy active=True) |

Params: `limit`, `offset`

### Category API - `/api/v1/zalo/categories/*`

| Method | Route | Mô tả |
|---|---|---|
| GET | `/api/v1/zalo/categories/list` | Danh sách danh mục (pos.category) |
| GET | `/api/v1/zalo/categories/<id>/products` | Sản phẩm theo danh mục |

Params: `limit`, `offset`

### Product API - `/api/v1/zalo/products/*`

| Method | Route | Mô tả |
|---|---|---|
| POST | `/api/v1/zalo/products/list` | Danh sách variant |
| POST | `/api/v1/zalo/products/detail` | Chi tiết sản phẩm |
| POST | `/api/v1/zalo/products/update-price` | Cập nhật giá sản phẩm (`x_zalo_price`, `list_price`, `standard_price`) |

Params: `limit`, `offset`, `query` (search), `sort` (name, -name, x_zalo_price, -x_zalo_price, create_date, -create_date, list_price, -list_price), `category_id`

### Contact API - `/api/v1/zalo/contacts/*`

| Method | Route | Mô tả |
|---|---|---|
| POST | `/api/v1/zalo/contacts/auth` | Auth bằng SĐT, tạo portal account |
| GET | `/api/v1/zalo/contacts/list` | Danh sách Zalo contacts |
| GET | `/api/v1/zalo/contacts/<id>` | Chi tiết contact |
| PUT | `/api/v1/zalo/contacts/<id>` | Cập nhật thông tin |
| GET | `/api/v1/zalo/contacts/<id>/addresses` | Danh sách địa chỉ |
| POST | `/api/v1/zalo/contacts/<id>/addresses` | Thêm địa chỉ |
| PUT | `/api/v1/zalo/contacts/<id>/addresses/<addr_id>` | Sửa địa chỉ |
| DELETE | `/api/v1/zalo/contacts/<id>/addresses/<addr_id>` | Xóa địa chỉ |

### Cart API - `/api/v1/zalo/cart/*`

| Method | Route | Mô tả |
|---|---|---|
| GET | `/api/v1/zalo/cart/<contact_id>` | Lấy giỏ hàng |
| POST | `/api/v1/zalo/cart/add` | Thêm sản phẩm |
| PUT | `/api/v1/zalo/cart/update` | Cập nhật số lượng |
| DELETE | `/api/v1/zalo/cart/remove` | Xóa sản phẩm |
| DELETE | `/api/v1/zalo/cart/clear/<contact_id>` | Xóa giỏ hàng |

### Order API - `/api/v1/zalo/orders/*`

| Method | Route | Mô tả |
|---|---|---|
| GET | `/api/v1/zalo/orders/<contact_id>/list` | Danh sách đơn |
| GET | `/api/v1/zalo/orders/<id>` | Chi tiết đơn |
| POST | `/api/v1/zalo/orders/create` | Tạo đơn từ giỏ hàng |
| POST | `/api/v1/zalo/orders/<id>/cancel` | Hủy đơn |

### Image API

| Method | Route | Mô tả |
|---|---|---|
| GET | `/api/v1/zalo/image/<model>/<id>/<field>` | Trả ảnh binary |

## Auth flow

1. Client gọi `POST /api/v1/zalo/contacts/auth` với `phone`
2. Backend tạo/resolve `res.partner` + `hlv.loyalty.portal.account`
3. Backend trả về `token` (HMAC-SHA256)
4. Client gửi `Authorization: Bearer <token>` cho các request khác

Token format: `{partner_id}.{timestamp}.{signature}`
Secret key: lưu trong `ir.config_parameter` key `zalo_api_secret`
Dev mode: nếu chưa config secret, dùng fallback `hlv_zalo_dev_secret_2026` (bỏ qua expiry check)

### Order Chatter & Hủy Đơn
- Đơn hàng tạo mới hoặc bị hủy từ Zalo Mini App sẽ tự động ghi log vào **Chatter (message_post)** trên `sale.order` với thông tin chi tiết (Tên khách hàng, SĐT, Thời gian, Ghi chú, Voucher, Lý do hủy) sử dụng `markupsafe.Markup`.
- Khi đơn hàng bị hủy từ Zalo Mini App (`/api/v1/zalo/orders/cancel`), hệ thống tự động bật cờ `x_plan_need_cancel = True` ("Cần hủy") trên `sale.order` để bộ phận kho/sales dễ dàng nhận biết và lọc đơn cần hủy.
- Giao diện danh sách "Đơn hàng Zalo Mini App" (`view_order_zalo_tree`) được tối ưu với đầy đủ các cột trạng thái: **Cần hủy**, **Số báo giá**, **Ngày đặt hàng**, **Ngày giao hàng**, **Khách hàng**, **Chuyên viên sales**, **Hoạt động**, **Tổng**, **Trạng thái đơn hàng**, **Trạng thái giao hàng**, **Trạng thái hóa đơn**, và **Thẻ**.

### CORS & Security
- Tất cả API routes đều hỗ trợ `OPTIONS` preflight request (`methods=[..., "OPTIONS"]`) và phản hồi 200 OK kèm CORS headers.
- CORS Origin mặc định là `*` (Configurable qua `ir.config_parameter` `zalo_api_cors_origin`).
- Xác thực sử dụng HMAC SHA256 Token với format `{partner_id}.{timestamp}.{signature}`.

### Quản lý Tài khoản Portal Zalo Mini App (Khách hàng cá nhân)
- **Model sử dụng**: `hlv.loyalty.portal.account` (kế thừa từ `hlv_loyalty`).
- **Phân biệt đối tượng**: Đóng vai trò là trang quản lý riêng biệt cho các khách hàng cá nhân (`is_company = False` và `x_is_zalo_account = True`). Trang Portal Loyalty ở module `hlv_loyalty` dành riêng cho doanh nghiệp (`is_company = True`).
- **Vị trí Menu**:
  - `Loyalty > Cấu hình > Tài khoản Portal Zalo` (`menu_loyalty_zalo_portal_account`)
  - `Zalo Mini App > Quản lý > Tài khoản Portal Zalo` (`menu_zalo_miniapp_portal_account_app`)
- **Tính năng**: Quản lý thông tin đăng nhập (username, portal_phone), Reset mật khẩu (`action_reset_password_wizard`), và Tính lại điểm Loyalty (`action_recalculate_points_wizard`).