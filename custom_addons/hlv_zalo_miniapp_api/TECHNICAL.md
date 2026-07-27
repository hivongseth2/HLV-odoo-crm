# Tài liệu kỹ thuật module `hlv_zalo_miniapp_api`

## Mục đích

Module cung cấp REST API cho Zalo Mini App, thực hiện export data để phát triển mini app.
Module này **không xây dựng giao diện frontend** - chỉ chứa API endpoints.

## Cấu trúc thư mục

```
hlv_zalo_miniapp_api/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── product_product.py      # Mở rộng product.product: x_zalo_price, x_active_zalo
│   └── res_partner.py           # Mở rộng res.partner: x_is_zalo_account
├── controllers/
│   ├── __init__.py
│   ├── category_api.py          # API danh mục (pos.category)
│   ├── product_api.py           # API sản phẩm (product.product variant)
│   ├── contact_api.py           # API contact (auth, CRUD, addresses)
│   ├── cart_api.py              # API giỏ hàng (sale.order draft)
│   └── order_api.py             # API đơn hàng (list/detail/create/cancel)
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

### `res.partner` (kế thừa)

| Field | Type | Mô tả |
|---|---|---|
| `x_is_zalo_account` | Boolean | Đánh dấu contact đã đăng ký Zalo |

## API Endpoints

### Category API - `/api/v1/zalo/categories/*`

| Method | Route | Mô tả |
|---|---|---|
| GET | `/api/v1/zalo/categories/list` | Danh sách danh mục (pos.category) |
| GET | `/api/v1/zalo/categories/<id>/products` | Sản phẩm theo danh mục |

Params: `limit`, `offset`

### Product API - `/api/v1/zalo/products/*`

| Method | Route | Mô tả |
|---|---|---|
| GET | `/api/v1/zalo/products/list` | Danh sách variant |
| GET | `/api/v1/zalo/products/<id>` | Chi tiết sản phẩm |

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

## Thông tin bổ sung

### Tồn kho
- Sử dụng `product.product.free_qty` - tồn khả dụng, không bao gồm hàng đang giữ chỗ

### Giá
- `x_zalo_price` - giá chính cho Zalo App
- `list_price` - giá gốc từ Odoo
- `promotional_price` - giá khuyến mãi từ pricelist (nếu có)

### Voucher
- Code voucher verify có sẵn trong order_api (gọi `hlv.loyalty.voucher`)
- Chưa export API redeem riêng (chờ phê duyệt Zalo)