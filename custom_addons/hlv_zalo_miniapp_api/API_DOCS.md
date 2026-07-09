# Tài liệu API - HLV Zalo Mini App

**Base URL**: `https://<your-odoo-domain>`

## Authentication

### Token Auth
- Hầu hết API dùng token HMAC-SHA256
- Header: `Authorization: Bearer <token>`
- Token nhận từ `POST /api/v1/zalo/contacts/auth`
- Format: `{partner_id}.{timestamp}.{signature}`
- Hết hạn: 30 ngày (production)
- Dev mode (secret mặc định): không kiểm tra hết hạn

### Cài đặt Secret Key cho Production
Vào Settings > Technical > System Parameters:
- Key: `zalo_api_secret`
- Value: `<your-secret-key>`

---

## Category API

### POST /api/v1/zalo/categories/list
Danh sách danh mục POS.

**Body**:
```json
{
  "limit": 20,
  "offset": 0
}
```

**Response**:
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

### POST /api/v1/zalo/categories/<id>/products
Lấy sản phẩm theo danh mục. `id` có thể là `x_misa_id` hoặc ID nội bộ Odoo.

**Body**:
```json
{
  "limit": 20,
  "offset": 0
}
```

**Response**:
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

---

## Product API

### POST /api/v1/zalo/products/list
Danh sách sản phẩm variant (chỉ lấy `x_active_zalo=True`).

**Body**:
```json
{
  "limit": 20,
  "offset": 0,
  "query": "iphone",
  "sort": "name",
  "category_id": 0
}
```

**Params**:
| Field | Type | Default | Mô tả |
|---|---|---|---|
| limit | int | 20 | Số lượng |
| offset | int | 0 | Vị trí bắt đầu |
| query | string | "" | Tìm kiếm (name, code, barcode) |
| sort | string | "name" | Sort: name, -name, x_zalo_price, -x_zalo_price, create_date, -create_date, list_price, -list_price |
| category_id | int | 0 | Lọc theo danh mục |

**Response**:
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

### GET /api/v1/zalo/products/<id>
Chi tiết sản phẩm.

**Response** (thêm):
```json
{
  "success": true,
  "data": {
    "...": "...",
    "description_full": "Mô tả đầy đủ",
    "standard_price": 20000000,
    "volume": 0.1,
    "images": [
      "/api/v1/zalo/image/product.template/10/image_1920"
    ]
  }
}
```

---

## Contact API

### POST /api/v1/zalo/contacts/auth
Đăng ký/Đăng nhập bằng SĐT.

**Body**:
```json
{
  "phone": "0901234567"
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "contact_id": 1,
    "name": "Nguyễn Văn A",
    "phone": "0901234567",
    "email": "",
    "token": "1.1741500000.abc123def456",
    "is_new": false
  }
}
```

### POST /api/v1/zalo/contacts/list
**Auth**: Bearer token required

**Body**:
```json
{
  "limit": 20,
  "offset": 0
}
```

### GET /api/v1/zalo/contacts/<id>
**Auth**: Bearer token required

### PUT /api/v1/zalo/contacts/<id>
**Auth**: Bearer token required

**Body**:
```json
{
  "name": "Nguyễn Văn A",
  "email": "a@example.com",
  "phone": "0901234567",
  "street": "123 Lê Lợi",
  "city": "Hồ Chí Minh",
  "zip": "70000"
}
```

### GET /api/v1/zalo/contacts/<id>/addresses
**Auth**: Bearer token required

### POST /api/v1/zalo/contacts/<id>/addresses
**Auth**: Bearer token required

**Body**:
```json
{
  "name": "Nhà riêng",
  "street": "456 Nguyễn Huệ",
  "city": "Hồ Chí Minh",
  "phone": "0901234567",
  "type": "delivery"
}
```

### PUT /api/v1/zalo/contacts/<id>/addresses/<addr_id>
**Auth**: Bearer token required

### DELETE /api/v1/zalo/contacts/<id>/addresses/<addr_id>
**Auth**: Bearer token required

---

## Cart API

### GET /api/v1/zalo/cart/<contact_id>
Lấy giỏ hàng hiện tại (tạo mới nếu chưa có).

### POST /api/v1/zalo/cart/add
**Body**:
```json
{
  "contact_id": 1,
  "product_id": 42,
  "quantity": 2
}
```

### PUT /api/v1/zalo/cart/update
**Body**:
```json
{
  "contact_id": 1,
  "line_id": 12,
  "quantity": 5
}
```

### DELETE /api/v1/zalo/cart/remove
**Body**:
```json
{
  "contact_id": 1,
  "line_id": 12
}
```

### DELETE /api/v1/zalo/cart/clear/<contact_id>

---

## Order API

### POST /api/v1/zalo/orders/<contact_id>/list
**Body**:
```json
{
  "limit": 20,
  "offset": 0,
  "state": "sale"
}
```
`state` optional: draft, sent, sale, done, cancel

### GET /api/v1/zalo/orders/<id>

### POST /api/v1/zalo/orders/create
**Body**:
```json
{
  "contact_id": 1,
  "address_id": 2,
  "note": "Giao trước 18h",
  "voucher_code": "VHQ-XXXXX"
}
```

### POST /api/v1/zalo/orders/<id>/cancel
**Body**:
```json
{
  "contact_id": 1,
  "reason": "Đổi ý không mua nữa"
}
```

---

## Image API

### GET /api/v1/zalo/image/<model>/<id>/<field>
Trả ảnh binary.
- model: tên model Odoo (vd: pos.category, product.product, product.template)
- id: ID bản ghi
- field: image_128, image_1920, ...

---

## Error Response Format

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Mô tả lỗi"
  }
}
```

### Error Codes
| Code | HTTP Status | Mô tả |
|---|---|---|
| NOT_FOUND | 404 | Không tìm thấy |
| INVALID_INPUT | 400 | Dữ liệu không hợp lệ |
| AUTH_REQUIRED | 401 | Thiếu token |
| INVALID_TOKEN | 401 | Token sai/hết hạn |
| FORBIDDEN | 403 | Không có quyền |
| VOUCHER_ERROR | 400 | Lỗi voucher |
| ORDER_ERROR | 400 | Lỗi tạo đơn |
| INVALID_STATE | 400 | Trạng thái không hợp lệ |
| SERVER_ERROR | 500 | Lỗi server |

---

## Luồng sử dụng

```
1. Auth: POST /contacts/auth → lấy token + contact_id
2. Xem categories: POST /categories/list
3. Xem products: POST /products/list?category_id=...
4. Cart: GET /cart/{contact_id} → POST /cart/add → PUT /cart/update → DELETE /cart/remove
5. Address: POST /contacts/{id}/addresses → GET addresses
6. Order: POST /orders/create → GET /orders/{id} → POST /orders/{id}/cancel