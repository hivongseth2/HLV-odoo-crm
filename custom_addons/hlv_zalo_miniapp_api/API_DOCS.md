# Tài liệu API - HLV Zalo Mini App

**Base URL**: `https://<your-odoo-domain>`

**Content-Type**: `application/json`

**Response Format Chung**:

| Kết quả | Format |
|---------|--------|
| Thành công | `{"success": true, "data": {...}}` |
| Thất bại | `{"success": false, "error": {"code": "...", "message": "..."}}` |

---

## Authentication

### Token Auth (HMAC-SHA256)

Hầu hết API yêu cầu `Authorization: Bearer <token>` header.

**Cách lấy token**: Gọi `POST /api/v1/zalo/contacts/auth` với số điện thoại.

**Token format**: `{partner_id}.{timestamp}.{signature}`

- `partner_id`: ID của `res.partner` trong Odoo
- `timestamp`: Unix timestamp (giây)
- `signature`: HMAC-SHA256 hex digest của chuỗi `"{partner_id}:{phone}:{timestamp}"`

**Hết hạn**:
- 30 ngày (kể từ timestamp trong token)

### Cài đặt Secret Key cho Production

Vào Settings > Technical > System Parameters:
- **Key**: `zalo_api_secret`
- **Value**: `<your-secret-key>` (tự chọn, bảo mật)

---

## 1. Banner API

### 1.1. Danh sách Banner

> **POST** `/api/v1/zalo/banners/list`

Lấy danh sách banner hiển thị trên trang chủ Zalo Mini App. Banner được lấy từ model `zalo.miniapp.banner`, sắp xếp theo `sequence` tăng dần.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `limit` | int | Optional | 10 | Số lượng banner tối đa (1-100) |
| `offset` | int | Optional | 0 | Vị trí bắt đầu lấy dữ liệu |

#### Request Example

```json
{
  "limit": 10,
  "offset": 0
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `total` | int | Tổng số banner đang active |
| `limit` | int | Số lượng đã yêu cầu |
| `offset` | int | Vị trí bắt đầu |
| `banners` | array[object] | Danh sách banner |

**Mỗi banner object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của banner |
| `name` | string | Tên banner |
| `link` | string | URL đích khi click (deep link hoặc external URL) |
| `image_url` | string | Relative URL ảnh banner (`/api/v1/zalo/image/zalo.miniapp.banner/{id}/image`) |

#### Response Example

```json
{
    "success": true,
    "data": {
        "banners": [
            {
                "id": 1,
                "name": "test",
                "link": "https://images.pexels.com/photos/459225/pexels-photo-459225.jpeg?cs=srgb&dl=daylight-environment-forest-459225.jpg&fm=jpg",
                "image_url": "/api/v1/zalo/image/zalo.miniapp.banner/1/image"
            }
        ],
        "total": 1,
        "limit": 10,
        "offset": 0
    }
}
```

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

## 2. Category API

### 2.1. Danh sách Danh mục

> **POST** `/api/v1/zalo/categories/list`

Lấy danh sách danh mục sản phẩm từ `pos.category`, sắp xếp theo `sequence, name`.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `limit` | int | Optional | 20 | Số lượng danh mục tối đa (1-100) |
| `offset` | int | Optional | 0 | Vị trí bắt đầu lấy dữ liệu |

#### Request Example

```json
{
  "limit": 20,
  "offset": 0
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `total` | int | Tổng số danh mục |
| `limit` | int | Số lượng đã yêu cầu |
| `offset` | int | Vị trí bắt đầu |
| `categories` | array[object] | Danh sách danh mục |

**Mỗi category object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID nội bộ Odoo của `pos.category` |
| `x_misa_id` | int hoặc null | ID từ MISA (nếu có field `x_misa_id`) |
| `name` | string | Tên danh mục |
| `sequence` | int | Thứ tự sắp xếp |
| `parent_id` | int hoặc null | ID danh mục cha |
| `parent_name` | string hoặc null | Tên danh mục cha |
| `image_url` | string hoặc null | Relative URL ảnh danh mục (`/api/v1/zalo/image/pos.category/{id}/image_128`) |

#### Response Example

```json
{
  "success": true,
  "data": {
    "total": 50,
    "limit": 20,
    "offset": 0,
    "categories": [
      {
        "id": 5,
        "x_misa_id": 100,
        "name": "Điện thoại",
        "sequence": 1,
        "parent_id": null,
        "parent_name": null,
        "image_url": "/api/v1/zalo/image/pos.category/5/image_128"
      }
    ]
  }
}
```

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 2.2. Sản phẩm theo Danh mục

> **POST** `/api/v1/zalo/categories/products`

Lấy danh sách sản phẩm (variant) thuộc một danh mục. Chỉ lấy sản phẩm có `x_active_zalo = True`, `active = True`, `sale_ok = True`.

`category_id` có thể là `x_misa_id` hoặc ID nội bộ Odoo của `pos.category`.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `category_id` | int | **Required** | — | ID danh mục (x_misa_id hoặc Odoo ID) |
| `limit` | int | Optional | 20 | Số lượng sản phẩm tối đa (1-100) |
| `offset` | int | Optional | 0 | Vị trí bắt đầu lấy dữ liệu |

#### Request Example

```json
{
  "category_id": 1,
  "limit": 20,
  "offset": 0
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `category_id` | int | ID nội bộ Odoo của danh mục |
| `category_name` | string | Tên danh mục |
| `total` | int | Tổng số sản phẩm trong danh mục |
| `limit` | int | Số lượng đã yêu cầu |
| `offset` | int | Vị trí bắt đầu |
| `products` | array[object] | Danh sách sản phẩm variant |

**Mỗi product object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `product.product` |
| `template_id` | int | ID của `product.template` |
| `name` | string | Tên hiển thị (display_name) |
| `default_code` | string hoặc null | Mã sản phẩm |
| `barcode` | string hoặc null | Mã vạch |
| `x_zalo_price` | float | Giá Zalo App |
| `list_price` | float | Giá niêm yết |
| `free_qty` | float | Tồn kho khả dụng |
| `uom` | string | Đơn vị tính |
| `image_url` | string hoặc null | Relative URL ảnh sản phẩm |

#### Response Example

```json
{
  "success": true,
  "data": {
    "category_id": 5,
    "category_name": "Điện thoại",
    "total": 10,
    "limit": 20,
    "offset": 0,
    "products": [
      {
        "id": 42,
        "template_id": 10,
        "name": "iPhone 15 128GB",
        "default_code": "IP15-128",
        "barcode": "123456789",
        "x_zalo_price": 25000000,
        "list_price": 26000000,
        "free_qty": 15.0,
        "uom": "Cái",
        "image_url": "/api/v1/zalo/image/product.product/42/image_128"
      }
    ]
  }
}
```

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `category_id` |
| `NOT_FOUND` | 404 | Danh mục không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

## 3. Product API

### 3.1. Danh sách Sản phẩm

> **POST** `/api/v1/zalo/products/list`

Lấy danh sách sản phẩm variant với các tùy chọn tìm kiếm, sắp xếp, lọc theo danh mục. Chỉ lấy sản phẩm có `x_active_zalo = True`, `active = True`, `sale_ok = True`.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `limit` | int | Optional | 20 | Số lượng sản phẩm tối đa (1-100) |
| `offset` | int | Optional | 0 | Vị trí bắt đầu lấy dữ liệu |
| `query` | string | Optional | "" | Từ khóa tìm kiếm (tìm trong `name`, `default_code`, `barcode`) |
| `sort` | string | Optional | "name" | Cách sắp xếp (xem bảng bên dưới) |
| `category_id` | int | Optional | 0 | Lọc theo danh mục (ID nội bộ Odoo của `pos.category`) |

**Giá trị `sort`**:

| Giá trị | Mô tả |
|---------|-------|
| `name` | Tên A→Z (mặc định) |
| `-name` | Tên Z→A |
| `x_zalo_price` | Giá Zalo tăng dần |
| `-x_zalo_price` | Giá Zalo giảm dần |
| `create_date` | Ngày tạo cũ→mới |
| `-create_date` | Ngày tạo mới→cũ |
| `list_price` | Giá niêm yết tăng dần |
| `-list_price` | Giá niêm yết giảm dần |

#### Request Example

```json
{
  "limit": 20,
  "offset": 0,
  "query": "iphone",
  "sort": "name",
  "category_id": 0
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `total` | int | Tổng số sản phẩm thỏa điều kiện |
| `limit` | int | Số lượng đã yêu cầu |
| `offset` | int | Vị trí bắt đầu |
| `products` | array[object] | Danh sách sản phẩm variant |

**Mỗi product object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `product.product` |
| `template_id` | int | ID của `product.template` |
| `name` | string | Tên hiển thị (display_name) |
| `template_name` | string | Tên template (product_tmpl_id.name) |
| `default_code` | string hoặc null | Mã sản phẩm |
| `barcode` | string hoặc null | Mã vạch |
| `x_zalo_price` | float | Giá Zalo App |
| `list_price` | float | Giá niêm yết |
| `promotional_price` | float hoặc null | Giá khuyến mãi (từ pricelist active đầu tiên, nếu khác `x_zalo_price`) |
| `free_qty` | float | Tồn kho khả dụng |
| `uom` | string | Đơn vị tính |
| `weight` | float | Trọng lượng |
| `category` | object hoặc null | Danh mục: `{id, name}` |
| `attributes` | array[object] | Danh sách thuộc tính: `{id, name, value}` |
| `image_url` | string hoặc null | Relative URL ảnh sản phẩm |
| `description` | string | Mô tả ngắn (`description_sale`) |
| `description_html` | string | Mô tả HTML (`description`) |

#### Response Example

```json
{
  "success": true,
  "data": {
    "total": 100,
    "limit": 20,
    "offset": 0,
    "products": [
      {
        "id": 42,
        "template_id": 10,
        "name": "iPhone 15 128GB",
        "template_name": "iPhone 15",
        "default_code": "IP15-128",
        "barcode": "123456789",
        "x_zalo_price": 25000000,
        "list_price": 26000000,
        "promotional_price": 24000000,
        "free_qty": 15.0,
        "uom": "Cái",
        "weight": 0.2,
        "category": { "id": 5, "name": "Điện thoại" },
        "attributes": [
          { "id": 1, "name": "Màu sắc", "value": "Đen" }
        ],
        "image_url": "/api/v1/zalo/image/product.product/42/image_128",
        "description": "Mô tả ngắn",
        "description_html": "<p>Mô tả HTML</p>"
      }
    ]
  }
}
```

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 3.2. Chi tiết Sản phẩm

> **POST** `/api/v1/zalo/products/detail`

Lấy thông tin chi tiết của một sản phẩm variant, bao gồm ảnh phụ và giá vốn.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `product_id` | int | **Required** | — | ID của `product.product` |

#### Request Example

```json
{
  "product_id": 42
}
```

#### Response `data`

Trả về tất cả các field giống **3.1. Danh sách Sản phẩm**, bổ sung thêm:

| Field | Type | Mô tả |
|-------|------|-------|
| `description_full` | string | Mô tả đầy đủ (`description`) |
| `standard_price` | float | Giá vốn |
| `volume` | float | Thể tích |
| `images` | array[string] | Danh sách URL ảnh phụ (từ `product.multi.image` hoặc `product.template.image_1920`) |

#### Response Example

```json
{
  "success": true,
  "data": {
    "id": 42,
    "name": "iPhone 15 128GB",
    "x_zalo_price": 25000000,
    "free_qty": 15.0,
    "images": [
      "/api/v1/zalo/image/product.template/10/image_1920"
    ],
    "attributes": [
      { "id": 1, "name": "Màu sắc", "value": "Đen" }
    ],
    "description_full": "<p>Mô tả đầy đủ</p>",
    "standard_price": 20000000,
    "volume": 0.1
  }
}
```

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `product_id` |
| `NOT_FOUND` | 404 | Sản phẩm không tồn tại, không active, hoặc `x_active_zalo = False` |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

## 4. Contact API

### 4.1. Đăng ký / Đăng nhập bằng SĐT

> **POST** `/api/v1/zalo/contacts/auth`

Xác thực người dùng bằng số điện thoại. Nếu số điện thoại chưa tồn tại, tự động tạo `res.partner` mới và `hlv.loyalty.portal.account`.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `phone` | string | **Required** | — | Số điện thoại Việt Nam (hỗ trợ nhiều format: 090..., 8490..., 08490...) |

#### Request Example

```json
{
  "phone": "0901234567"
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `contact_id` | int | ID của `res.partner` |
| `name` | string | Tên khách hàng |
| `phone` | string | Số điện thoại đã chuẩn hóa (đã loại bỏ ký tự không phải số) |
| `email` | string | Email (nếu có) |
| `token` | string | Bearer token (HMAC-SHA256) dùng cho các request sau |
| `is_new` | bool | `true` nếu vừa tạo mới contact, `false` nếu đã tồn tại |

#### Response Example

```json
{
  "success": true,
  "data": {
    "contact_id": 1,
    "name": "Zalo 0901234567",
    "phone": "0901234567",
    "email": "",
    "token": "1.1741500000.abc123def456",
    "is_new": true
  }
}
```

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Số điện thoại trống hoặc không hợp lệ |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 4.2. Đăng nhập bằng Zalo Phone Token

> **POST** `/api/v1/zalo/contacts/auth/zalo-phone`

Lấy số điện thoại thật từ Zalo Graph API (`graph.zalo.me/v2.0/me/info`) và tự động đăng nhập/tạo tài khoản.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `token` | string | **Required** | — | Phone token từ Zalo (dùng làm `code` khi gọi Zalo API) |
| `access_token` | string | **Required** | — | Access token từ Zalo (dùng làm `access_token` khi gọi Zalo API) |

#### Request Example

```json
{
  "token": "zalo_phone_token_here",
  "access_token": "zalo_access_token_here"
}
```

#### Yêu cầu cấu hình

Cần cấu hình **Zalo Secret Key** trong System Parameters:
- Key: `hlv_loyalty.zalo_secret_key` hoặc `zalo.secret_key`
- Value: Secret key từ Zalo Developer Console

#### Response `data`

Giống với **4.1. Đăng ký / Đăng nhập bằng SĐT**.

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `token` hoặc `access_token` |
| `CONFIG_ERROR` | 503 | Thiếu cấu hình Zalo Secret Key trên Odoo |
| `ZALO_ERROR` | 400 | Zalo từ chối token hoặc không trả về số điện thoại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |
| — | 502 | Lỗi kết nối đến Zalo Graph API |

---

### 4.3. Danh sách Contact

> **POST** `/api/v1/zalo/contacts/list`

**Auth**: Bearer token required

Lấy danh sách tất cả contact có `x_is_zalo_account = True`.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `limit` | int | Optional | 20 | Số lượng contact tối đa (1-100) |
| `offset` | int | Optional | 0 | Vị trí bắt đầu lấy dữ liệu |

#### Request Example

```json
{
  "limit": 20,
  "offset": 0
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `total` | int | Tổng số Zalo contacts |
| `limit` | int | Số lượng đã yêu cầu |
| `offset` | int | Vị trí bắt đầu |
| `contacts` | array[object] | Danh sách contact |

**Mỗi contact object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `res.partner` |
| `name` | string | Tên |
| `phone` | string | Số điện thoại |
| `mobile` | string | Số di động |
| `email` | string | Email |
| `street` | string | Địa chỉ |
| `city` | string | Thành phố |

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `AUTH_REQUIRED` | 401 | Thiếu `Authorization: Bearer` header |
| `INVALID_TOKEN` | 401 | Token không hợp lệ hoặc đã hết hạn |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 4.4. Chi tiết Contact

> **POST** `/api/v1/zalo/contacts/detail`

**Auth**: Bearer token required

Lấy thông tin chi tiết của một contact, bao gồm điểm Loyalty và danh sách địa chỉ giao hàng.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` |

#### Request Example

```json
{
  "contact_id": 1
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `res.partner` |
| `name` | string | Tên |
| `phone` | string | Số điện thoại |
| `mobile` | string | Số di động |
| `email` | string | Email |
| `street` | string | Địa chỉ |
| `city` | string | Thành phố |
| `state` | string | Tên tỉnh/thành phố (nếu có) |
| `country` | string | Tên quốc gia (nếu có) |
| `zip` | string | Mã bưu điện |
| `total_points` | int | Tổng điểm Loyalty (từ `loyalty_total_points`) |
| `exchange_points` | int | Điểm đã đổi (từ `loyalty_exchange_points`) |
| `tier` | object hoặc null | Thông tin hạng thành viên: `{name, icon, image_url}` |
| `addresses` | array[object] | Danh sách địa chỉ (type: delivery, other, invoice) |

**Mỗi address object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `res.partner` (child) |
| `name` | string | Tên địa chỉ |
| `street` | string | Địa chỉ |
| `street2` | string | Địa chỉ bổ sung |
| `city` | string | Thành phố |
| `state` | string | Tên tỉnh/thành phố |
| `country` | string | Tên quốc gia |
| `zip` | string | Mã bưu điện |
| `phone` | string | Số điện thoại (fallback về SĐT contact chính) |
| `type` | string | Loại địa chỉ: `delivery`, `other`, `invoice` |

#### Response Example

```json
{
  "success": true,
  "data": {
    "id": 1,
    "name": "Nguyễn Văn A",
    "phone": "0901234567",
    "total_points": 1500,
    "exchange_points": 500,
    "tier": {
      "name": "Gold",
      "icon": "gold_icon.png",
      "image_url": ""
    },
    "addresses": [
      {
        "id": 5,
        "name": "Nhà riêng",
        "street": "123 Lê Lợi",
        "street2": "",
        "city": "Hồ Chí Minh",
        "state": "",
        "country": "",
        "zip": "",
        "phone": "0901234567",
        "type": "delivery"
      }
    ]
  }
}
```

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `AUTH_REQUIRED` | 401 | Thiếu `Authorization: Bearer` header |
| `INVALID_TOKEN` | 401 | Token không hợp lệ hoặc đã hết hạn |
| `INVALID_INPUT` | 400 | Thiếu `contact_id` |
| `NOT_FOUND` | 404 | Contact không tồn tại hoặc không active |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 4.5. Cập nhật Contact

> **PUT** `/api/v1/zalo/contacts/update`

**Auth**: Bearer token required

Cập nhật thông tin cơ bản của contact.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` |
| `name` | string | Optional | — | Tên mới |
| `email` | string | Optional | — | Email mới |
| `phone` | string | Optional | — | Số điện thoại mới (tự động chuẩn hóa) |
| `street` | string | Optional | — | Địa chỉ mới |
| `city` | string | Optional | — | Thành phố mới |
| `zip` | string | Optional | — | Mã bưu điện mới |

#### Request Example

```json
{
  "contact_id": 1,
  "name": "Nguyễn Văn A",
  "email": "a@example.com",
  "phone": "0901234567",
  "street": "123 Lê Lợi",
  "city": "Hồ Chí Minh",
  "zip": "70000"
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `res.partner` |
| `name` | string | Tên sau khi cập nhật |
| `message` | string | "Đã cập nhật" |

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `AUTH_REQUIRED` | 401 | Thiếu `Authorization: Bearer` header |
| `INVALID_TOKEN` | 401 | Token không hợp lệ hoặc đã hết hạn |
| `INVALID_INPUT` | 400 | Thiếu `contact_id` |
| `NOT_FOUND` | 404 | Contact không tồn tại hoặc không active |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 4.6. Danh sách Địa chỉ

> **POST** `/api/v1/zalo/contacts/addresses/list`

**Auth**: Bearer token required

Lấy danh sách địa chỉ giao hàng của một contact.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` chính |

#### Request Example

```json
{
  "contact_id": 1
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `addresses` | array[object] | Danh sách địa chỉ (cấu trúc giống mục 4.4) |

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `AUTH_REQUIRED` | 401 | Thiếu `Authorization: Bearer` header |
| `INVALID_TOKEN` | 401 | Token không hợp lệ hoặc đã hết hạn |
| `INVALID_INPUT` | 400 | Thiếu `contact_id` |
| `NOT_FOUND` | 404 | Contact không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 4.7. Tạo Địa chỉ mới

> **POST** `/api/v1/zalo/contacts/addresses/create`

**Auth**: Bearer token required

Thêm một địa chỉ giao hàng mới cho contact.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` chính |
| `street` | string | **Required** | — | Địa chỉ |
| `city` | string | **Required** | — | Thành phố |
| `name` | string | Optional | Tên contact | Tên địa chỉ (vd: "Nhà riêng") |
| `street2` | string | Optional | "" | Địa chỉ bổ sung |
| `state_id` | int | Optional | — | ID của `res.country.state` |
| `country_id` | int | Optional | — | ID của `res.country` |
| `zip` | string | Optional | "" | Mã bưu điện |
| `phone` | string | Optional | SĐT contact | Số điện thoại liên hệ |
| `type` | string | Optional | "delivery" | Loại địa chỉ: `delivery`, `invoice`, `other` |

#### Request Example

```json
{
  "contact_id": 1,
  "name": "Nhà riêng",
  "street": "456 Nguyễn Huệ",
  "city": "Hồ Chí Minh",
  "phone": "0901234567",
  "type": "delivery"
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID địa chỉ mới tạo |
| `name` | string | Tên địa chỉ |
| `street` | string | Địa chỉ |
| `street2` | string | Địa chỉ bổ sung |
| `city` | string | Thành phố |
| `phone` | string | Số điện thoại |
| `type` | string | Loại địa chỉ |

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `AUTH_REQUIRED` | 401 | Thiếu `Authorization: Bearer` header |
| `INVALID_TOKEN` | 401 | Token không hợp lệ hoặc đã hết hạn |
| `INVALID_INPUT` | 400 | Thiếu `contact_id`, `street`, hoặc `city` |
| `NOT_FOUND` | 404 | Contact không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 4.8. Cập nhật Địa chỉ

> **PUT** `/api/v1/zalo/contacts/addresses/update`

**Auth**: Bearer token required

Cập nhật thông tin một địa chỉ.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `address_id` | int | **Required** | — | ID của địa chỉ (`res.partner` child) |
| `name` | string | Optional | — | Tên địa chỉ |
| `street` | string | Optional | — | Địa chỉ |
| `street2` | string | Optional | — | Địa chỉ bổ sung |
| `city` | string | Optional | — | Thành phố |
| `zip` | string | Optional | — | Mã bưu điện |
| `phone` | string | Optional | — | Số điện thoại |
| `type` | string | Optional | — | Loại địa chỉ: `delivery`, `invoice`, `other` |
| `state_id` | int | Optional | — | ID của `res.country.state` |
| `country_id` | int | Optional | — | ID của `res.country` |

#### Request Example

```json
{
  "address_id": 12,
  "street": "789 Lê Duẩn",
  "city": "Hồ Chí Minh"
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID địa chỉ |
| `name` | string | Tên địa chỉ |
| `street` | string | Địa chỉ |
| `street2` | string | Địa chỉ bổ sung |
| `city` | string | Thành phố |
| `phone` | string | Số điện thoại |
| `type` | string | Loại địa chỉ |

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `AUTH_REQUIRED` | 401 | Thiếu `Authorization: Bearer` header |
| `INVALID_TOKEN` | 401 | Token không hợp lệ hoặc đã hết hạn |
| `INVALID_INPUT` | 400 | Thiếu `address_id` |
| `NOT_FOUND` | 404 | Địa chỉ không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 4.9. Xóa Địa chỉ

> **POST** `/api/v1/zalo/contacts/addresses/delete`

**Auth**: Bearer token required

Xóa một địa chỉ giao hàng.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `address_id` | int | **Required** | — | ID của địa chỉ cần xóa |

#### Request Example

```json
{
  "address_id": 12
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `message` | string | "Đã xóa địa chỉ" |

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `AUTH_REQUIRED` | 401 | Thiếu `Authorization: Bearer` header |
| `INVALID_TOKEN` | 401 | Token không hợp lệ hoặc đã hết hạn |
| `INVALID_INPUT` | 400 | Thiếu `address_id` |
| `NOT_FOUND` | 404 | Địa chỉ không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

## 5. Cart API

Giỏ hàng sử dụng `sale.order` với `state = draft` và `team_id = False`. Mỗi contact chỉ có **một** giỏ hàng draft duy nhất.

### 5.1. Lấy Giỏ hàng

> **POST** `/api/v1/zalo/cart/get`

Lấy thông tin giỏ hàng hiện tại của contact. Tự động tạo giỏ hàng mới nếu chưa có.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` |

#### Request Example

```json
{
  "contact_id": 1
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `sale.order` (giỏ hàng) |
| `partner_id` | int | ID của contact |
| `partner_name` | string | Tên contact |
| `state` | string | Luôn là `"draft"` |
| `lines` | array[object] | Danh sách dòng sản phẩm (chỉ gồm sản phẩm có `x_active_zalo = True`) |
| `total` | float | Tổng tiền hàng (chưa thuế) |
| `line_count` | int | Số dòng sản phẩm |
| `create_date` | string | Ngày tạo giỏ hàng |

**Mỗi line object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `sale.order.line` |
| `product_id` | int | ID của `product.product` |
| `product_name` | string | Tên sản phẩm |
| `product_code` | string hoặc null | Mã sản phẩm |
| `quantity` | float | Số lượng |
| `price_unit` | float | Đơn giá |
| `x_zalo_price` | float | Giá Zalo App |
| `subtotal` | float | Thành tiền |
| `image_url` | string hoặc null | URL ảnh sản phẩm |

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `contact_id` |
| `NOT_FOUND` | 404 | Contact không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 5.2. Thêm Sản phẩm vào Giỏ

> **POST** `/api/v1/zalo/cart/add`

Thêm sản phẩm vào giỏ hàng. Nếu sản phẩm đã có trong giỏ, sẽ cộng dồn số lượng.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` |
| `product_id` | int | **Required** | — | ID của `product.product` |
| `quantity` | float | Optional | 1.0 | Số lượng (phải > 0) |

#### Request Example

```json
{
  "contact_id": 1,
  "product_id": 42,
  "quantity": 2
}
```

#### Response `data`

Giống **5.1. Lấy Giỏ hàng** (giỏ hàng sau khi thêm).

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `contact_id` hoặc `product_id`; `quantity <= 0` |
| `NOT_FOUND` | 404 | Contact không tồn tại; Sản phẩm không tồn tại/không active/không có `x_active_zalo` |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 5.3. Cập nhật Số lượng

> **PUT** `/api/v1/zalo/cart/update`

Cập nhật số lượng của một dòng sản phẩm trong giỏ hàng. Nếu `quantity <= 0`, dòng sản phẩm sẽ bị xóa.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` |
| `line_id` | int | **Required** | — | ID của `sale.order.line` |
| `quantity` | float | **Required** | — | Số lượng mới (nếu <= 0 sẽ xóa dòng) |

#### Request Example

```json
{
  "contact_id": 1,
  "line_id": 12,
  "quantity": 5
}
```

#### Response `data`

Giống **5.1. Lấy Giỏ hàng** (giỏ hàng sau khi cập nhật).

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `contact_id` hoặc `line_id` |
| `NOT_FOUND` | 404 | Contact không tồn tại; Dòng sản phẩm không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 5.4. Xóa Sản phẩm khỏi Giỏ

> **POST** `/api/v1/zalo/cart/remove`

Xóa một dòng sản phẩm khỏi giỏ hàng.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` |
| `line_id` | int | **Required** | — | ID của `sale.order.line` cần xóa |

#### Request Example

```json
{
  "contact_id": 1,
  "line_id": 12
}
```

#### Response `data`

Giống **5.1. Lấy Giỏ hàng** (giỏ hàng sau khi xóa).

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `contact_id` hoặc `line_id` |
| `NOT_FOUND` | 404 | Contact không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 5.5. Xóa toàn bộ Giỏ hàng

> **POST** `/api/v1/zalo/cart/clear`

Xóa tất cả sản phẩm trong giỏ hàng.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` |

#### Request Example

```json
{
  "contact_id": 1
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `message` | string | "Đã xóa giỏ hàng" |

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `contact_id` |
| `NOT_FOUND` | 404 | Contact không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

## 6. Order API

### 6.1. Danh sách Đơn hàng

> **POST** `/api/v1/zalo/orders/list`

Lấy danh sách đơn hàng của một contact (không bao gồm đơn draft).

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` |
| `limit` | int | Optional | 20 | Số lượng đơn tối đa (1-100) |
| `offset` | int | Optional | 0 | Vị trí bắt đầu lấy dữ liệu |
| `state` | string | Optional | — | Lọc theo trạng thái: `draft`, `sent`, `sale`, `done`, `cancel` |

#### Request Example

```json
{
  "contact_id": 1,
  "limit": 10,
  "offset": 0,
  "state": "sale"
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `total` | int | Tổng số đơn hàng thỏa điều kiện |
| `limit` | int | Số lượng đã yêu cầu |
| `offset` | int | Vị trí bắt đầu |
| `orders` | array[object] | Danh sách đơn hàng |

**Mỗi order object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `sale.order` |
| `name` | string | Mã đơn hàng (vd: SO001) |
| `partner_id` | int | ID của contact |
| `partner_name` | string | Tên contact |
| `partner_phone` | string | Số điện thoại contact |
| `state` | string | Trạng thái: `draft`, `sent`, `sale`, `done`, `cancel` |
| `date_order` | string | Ngày đặt hàng |
| `amount_untaxed` | float | Tổng tiền hàng (chưa thuế) |
| `amount_tax` | float | Tiền thuế |
| `amount_total` | float | Tổng thanh toán |
| `note` | string | Ghi chú đơn hàng |
| `lines` | array[object] | Danh sách dòng sản phẩm |
| `picking_info` | array[object] | Thông tin picking đã hoàn thành (`state = done`) |
| `shipping_address` | object hoặc null | Địa chỉ giao hàng: `{street, city}` |

**Mỗi line object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `sale.order.line` |
| `product_id` | int hoặc null | ID của `product.product` |
| `product_name` | string | Tên sản phẩm |
| `default_code` | string | Mã sản phẩm |
| `quantity` | float | Số lượng |
| `price_unit` | float | Đơn giá |
| `subtotal` | float | Thành tiền |
| `discount` | float | Chiết khấu (%) |

**Mỗi picking_info object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `stock.picking` |
| `type` | string | Loại picking (vd: "Giao hàng") |
| `state` | string | Trạng thái (luôn là `"done"`) |
| `scheduled_date` | string | Ngày dự kiến |

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `contact_id` |
| `NOT_FOUND` | 404 | Contact không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 6.2. Chi tiết Đơn hàng

> **POST** `/api/v1/zalo/orders/detail`

Lấy thông tin chi tiết của một đơn hàng.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `order_id` | int | **Required** | — | ID của `sale.order` |

#### Request Example

```json
{
  "order_id": 1
}
```

#### Response `data`

Giống cấu trúc order object trong **6.1. Danh sách Đơn hàng**.

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `order_id` |
| `NOT_FOUND` | 404 | Đơn hàng không tồn tại |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 6.3. Tạo Đơn hàng

> **POST** `/api/v1/zalo/orders/create`

Tạo đơn hàng từ danh sách sản phẩm do frontend gửi lên (frontend tự quản lý giỏ hàng). Backend sẽ tạo `sale.order` mới và confirm luôn.

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `contact_id` | int | **Required** | — | ID của `res.partner` |
| `items` | array[object] | **Required** | — | Danh sách sản phẩm từ giỏ hàng frontend |
| `address_id` | int | Optional | — | ID địa chỉ giao hàng (nếu không gửi, dùng ID contact) |
| `note` | string | Optional | "" | Ghi chú đơn hàng |
| `voucher_code` | string | Optional | "" | Mã voucher giảm giá (từ `hlv.loyalty.voucher`) |

**Mỗi item object**:

| Field | Type | Required | Mô tả |
|-------|------|----------|-------|
| `product_id` | int | **Required** | ID của `product.product` |
| `quantity` | float | **Required** | Số lượng (phải > 0) |

#### Request Example

```json
{
  "contact_id": 1,
  "items": [
    {"product_id": 42, "quantity": 2},
    {"product_id": 56, "quantity": 1}
  ],
  "address_id": 2,
  "note": "Giao trước 18h",
  "voucher_code": "VHQ-XXXXX"
}
```

#### Response `data`

Giống cấu trúc order object trong **6.1. Danh sách Đơn hàng**, bổ sung:

| Field | Type | Mô tả |
|-------|------|-------|
| `voucher_applied` | object | (chỉ xuất hiện nếu có voucher) Thông tin voucher đã áp dụng |

**voucher_applied object**:

| Field | Type | Mô tả |
|-------|------|-------|
| `valid` | bool | `true` |
| `voucher_code` | string | Mã voucher |
| `discount_type` | string | Loại giảm giá: `"percent"` hoặc `"fixed"` |
| `discount_value` | float | Giá trị giảm (số phần trăm hoặc số tiền) |
| `estimated_discount` | float | Số tiền giảm ước tính |

#### Voucher validation rules

1. Voucher phải tồn tại trong `hlv.loyalty.voucher`
2. Voucher phải có `state = "active"`
3. Voucher phải thuộc về contact (qua `partner_id` hoặc `parent_id`)
4. Voucher chưa hết hạn (`date_expiry` >= hiện tại)
5. Tổng đơn hàng >= `min_amount` của voucher

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `contact_id`; Giỏ hàng trống |
| `NOT_FOUND` | 404 | Contact không tồn tại |
| `VOUCHER_ERROR` | 400 | Mã voucher không hợp lệ, hết hạn, không đủ điều kiện |
| `ORDER_ERROR` | 400 | Không thể xác nhận đơn hàng (lỗi từ Odoo) |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

### 6.4. Hủy Đơn hàng

> **POST** `/api/v1/zalo/orders/cancel`

Hủy đơn hàng. Có thể hủy đơn ở mọi trạng thái ngoại trừ `done` (hoàn thành) và `cancel` (đã hủy).

#### Request Body

| Field | Type | Required | Default | Mô tả |
|-------|------|----------|---------|-------|
| `order_id` | int | **Required** | — | ID của `sale.order` |
| `contact_id` | int | **Required** | — | ID của `res.partner` (để xác thực quyền sở hữu) |
| `reason` | string | Optional | "" | Lý do hủy đơn |

#### Request Example

```json
{
  "order_id": 1,
  "contact_id": 1,
  "reason": "Đổi ý không mua nữa"
}
```

#### Response `data`

| Field | Type | Mô tả |
|-------|------|-------|
| `id` | int | ID của `sale.order` |
| `name` | string | Mã đơn hàng |
| `state` | string | Trạng thái sau khi hủy (`"cancel"`) |
| `message` | string | "Đã hủy đơn hàng thành công" |

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `INVALID_INPUT` | 400 | Thiếu `order_id` hoặc `contact_id` |
| `NOT_FOUND` | 404 | Đơn hàng không tồn tại |
| `FORBIDDEN` | 403 | Đơn hàng không thuộc về contact này |
| `INVALID_STATE` | 400 | Đơn hàng đã hoàn thành (`done`) hoặc đã hủy (`cancel`) |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

## 7. Image API

### 7.1. Lấy Ảnh

> **GET** `/api/v1/zalo/image/<model>/<int:rec_id>/<field>`

Trả về ảnh dạng binary (image/png) từ Odoo. Ảnh được lưu dưới dạng base64 trong database, API sẽ decode và trả về raw binary.

#### Path Parameters

| Parameter | Type | Mô tả |
|-----------|------|-------|
| `model` | string | Tên model Odoo. Các model được hỗ trợ: `product.product`, `product.template`, `pos.category`, `zalo.miniapp.banner`, `product.multi.image` |
| `rec_id` | int | ID của bản ghi |
| `field` | string | Tên field ảnh. Tùy theo model: `image_128` (thumbnail), `image_1920` (full size), `image` (banner) |

#### Request Examples

**Product Variant (thumbnail 128px)**:
```
GET /api/v1/zalo/image/product.product/42/image_128
```

**Product Template (full size 1920px)**:
```
GET /api/v1/zalo/image/product.template/10/image_1920
```

**Category Image**:
```
GET /api/v1/zalo/image/pos.category/5/image_128
```

**Banner Image**:
```
GET /api/v1/zalo/image/zalo.miniapp.banner/1/image
```

**Product Multi Image (ảnh phụ)**:
```
GET /api/v1/zalo/image/product.multi.image/15/image_1920
```

#### Response

- **Thành công**: Binary image data với `Content-Type: image/png`
- **Thất bại**: JSON error response

#### Error Codes

| Code | HTTP Status | Điều kiện |
|------|-------------|-----------|
| `NOT_FOUND` | 404 | Model không tồn tại; Bản ghi không tồn tại; Field không tồn tại; Không có ảnh |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

## 8. Error Codes

| Code | HTTP Status | Mô tả |
|------|-------------|-------|
| `NOT_FOUND` | 404 | Không tìm thấy tài nguyên (category, product, contact, order, address, image) |
| `INVALID_INPUT` | 400 | Dữ liệu đầu vào không hợp lệ hoặc thiếu field bắt buộc |
| `AUTH_REQUIRED` | 401 | Thiếu `Authorization: Bearer` header |
| `INVALID_TOKEN` | 401 | Token không hợp lệ hoặc đã hết hạn |
| `FORBIDDEN` | 403 | Không có quyền truy cập (đơn hàng không thuộc về bạn) |
| `VOUCHER_ERROR` | 400 | Lỗi voucher (không tồn tại, hết hạn, không đủ điều kiện) |
| `ORDER_ERROR` | 400 | Lỗi tạo đơn hàng (không thể xác nhận) |
| `INVALID_STATE` | 400 | Trạng thái đơn hàng không hợp lệ cho thao tác |
| `CONFIG_ERROR` | 503 | Thiếu cấu hình hệ thống (Zalo Secret Key) |
| `ZALO_ERROR` | 400 | Lỗi từ Zalo Graph API |
| `SERVER_ERROR` | 500 | Lỗi server không xác định |

---

## 9. Luồng sử dụng (User Flow)

```
1. AUTH
   POST /api/v1/zalo/contacts/auth
   → Nhận token + contact_id

2. XEM DANH MỤC
   POST /api/v1/zalo/categories/list
   → Danh sách category

3. XEM SẢN PHẨM
   POST /api/v1/zalo/categories/products  (lọc theo category)
   POST /api/v1/zalo/products/list        (tìm kiếm, sắp xếp)
   POST /api/v1/zalo/products/detail      (chi tiết + ảnh phụ)

4. GIỎ HÀNG
   POST /api/v1/zalo/cart/get             (xem giỏ)
   POST /api/v1/zalo/cart/add             (thêm SP)
   PUT /api/v1/zalo/cart/update           (sửa SL)
   POST /api/v1/zalo/cart/remove          (xóa SP)
   POST /api/v1/zalo/cart/clear           (xóa hết)

5. ĐỊA CHỈ (cần Bearer token)
   POST /api/v1/zalo/contacts/addresses/list     (xem địa chỉ)
   POST /api/v1/zalo/contacts/addresses/create   (thêm địa chỉ)
   PUT /api/v1/zalo/contacts/addresses/update    (sửa địa chỉ)
   POST /api/v1/zalo/contacts/addresses/delete   (xóa địa chỉ)

6. ĐẶT HÀNG
   POST /api/v1/zalo/orders/create       (tạo đơn từ giỏ hàng)
   POST /api/v1/zalo/orders/list         (xem lịch sử đơn)
   POST /api/v1/zalo/orders/detail       (xem chi tiết đơn)
   POST /api/v1/zalo/orders/cancel       (hủy đơn)
```

---

## 10. Ghi chú kỹ thuật

### Tồn kho
- Sử dụng `product.product.free_qty` - tồn khả dụng, không bao gồm hàng đang giữ chỗ.

### Giá
- `x_zalo_price`: Giá chính hiển thị trên Zalo Mini App (cấu hình trên `product.template`)
- `list_price`: Giá niêm yết từ Odoo
- `promotional_price`: Giá khuyến mãi từ pricelist active đầu tiên (nếu khác `x_zalo_price`)

### Voucher
- Voucher được verify qua model `hlv.loyalty.voucher`
- Áp dụng voucher bằng method `action_apply_loyalty_voucher` trên `sale.order`
- Nếu method không hoạt động, voucher code được ghi vào `note` của đơn hàng

### Phân trang
- Tất cả API list đều hỗ trợ `limit` (mặc định 20, tối đa 100) và `offset` (mặc định 0)