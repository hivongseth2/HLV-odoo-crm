# HLV Zalo Mini App — API Endpoints

> Base URL: `https://{domain}/api/v1`
>
> Authentication: Mini App phải đối chiếu SĐT Zalo với tài khoản portal loyalty và gửi kèm `partner_id` + `phone` cho các API theo khách hàng; không dùng session token.
>
> Content-Type: `application/json`
>
> Response format chung:
>
> ```json
> // Thành công
> { "success": true, "data": { ... } }
>
> // Lỗi
> { "success": false, "error": { "code": "ERROR_CODE", "message": "Mô tả lỗi" } }
> ```

---

## 1. Xác thực (Auth)

### 1.1 POST `/auth/zalo`

Xác thực user Zalo bằng SĐT portal loyalty → trả `partner_id` / API key.

**Input:**

```json
{
  "access_token": "zalo_access_token_string",
  "user_id": "zalo_user_id",
  "phone": "0901234567"
}
```

**Output (200):**

```json
{
  "success": true,
  "data": {
    "api_key": "bearer_token_for_subsequent_requests",
    "partner_id": 123,
    "name": "Nguyễn Văn A",
    "phone": "0901234567",
    "email": "a@example.com",
    "avatar": "https://...",
    "loyalty_points": 2500,
    "tier": "silver"
  }
}
```

---

## 2. Sản phẩm (Products)

### 2.1 GET `/categories`

Lấy danh sách danh mục sản phẩm.

**Input (Query params):** _Không bắt buộc_

| Param     | Type   | Mô tả                              |
| --------- | ------ | ----------------------------------- |
| parent_id | number | Lọc danh mục con (null = root)      |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "categories": [
      {
        "id": 1,
        "name": "Máy khoan",
        "image_url": "https://...",
        "parent_id": null,
        "child_count": 3
      },
      {
        "id": 2,
        "name": "Máy cắt",
        "image_url": "https://...",
        "parent_id": null,
        "child_count": 2
      }
    ]
  }
}
```

---

### 2.2 GET `/products`

Danh sách sản phẩm (có filter, sort, phân trang).

**Input (Query params):**

| Param       | Type   | Bắt buộc | Mô tả                                                                 |
| ----------- | ------ | --------- | ---------------------------------------------------------------------- |
| category_id | number | Không     | Lọc theo danh mục                                                     |
| search      | string | Không     | Tìm kiếm theo tên sản phẩm                                            |
| sort        | string | Không     | Sắp xếp: `price_asc`, `price_desc`, `best_seller`, `newest`           |
| page        | number | Không     | Trang hiện tại (mặc định: 1)                                          |
| limit       | number | Không     | Số sản phẩm/trang (mặc định: 20)                                      |
| featured    | bool   | Không     | `true` = chỉ lấy sản phẩm nổi bật (cho trang chủ)                     |
| best_seller | bool   | Không     | `true` = chỉ lấy sản phẩm bán chạy                                    |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "products": [
      {
        "id": 101,
        "name": "Máy khoan Bosch GSB 550",
        "price": 1290000,
        "original_price": 1590000,
        "discount_percent": 19,
        "image_url": "https://...",
        "sold_count": 358,
        "free_shipping": true,
        "voucher_label": "Giảm 50K",
        "gifts": ["Mũi khoan 6mm", "Hộp đựng"]
      }
    ],
    "total": 156,
    "page": 1,
    "limit": 20
  }
}
```

---

### 2.3 GET `/products/{id}`

Chi tiết 1 sản phẩm.

**Input (Path params):**

| Param | Type   | Bắt buộc | Mô tả      |
| ----- | ------ | --------- | ----------- |
| id    | number | Có        | ID sản phẩm |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "product": {
      "id": 101,
      "name": "Máy khoan Bosch GSB 550",
      "price": 1290000,
      "original_price": 1590000,
      "discount_percent": 19,
      "image_url": "https://...",
      "images": [
        "https://img1...",
        "https://img2..."
      ],
      "sold_count": 358,
      "free_shipping": true,
      "voucher_label": "Giảm 50K",
      "gifts": ["Mũi khoan 6mm", "Hộp đựng"],
      "description": "<p>HTML mô tả chi tiết sản phẩm...</p>",
      "specifications": [
        { "name": "Công suất", "value": "550W" },
        { "name": "Tốc độ", "value": "0-2800 rpm" }
      ],
      "category_id": 1,
      "category_name": "Máy khoan",
      "stock_available": true,
      "rating": 4.5,
      "review_count": 42
    }
  }
}
```

---

## 3. Banner

### 3.1 GET `/banners`

Lấy danh sách banner quảng cáo cho trang chủ.

**Input (Query params):** _Không bắt buộc_

| Param    | Type   | Mô tả                                |
| -------- | ------ | ------------------------------------- |
| position | string | Vị trí: `home_slider`, `category_top` |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "banners": [
      {
        "id": 1,
        "image_url": "https://...",
        "link": "/products?category_id=5",
        "sort_order": 1
      },
      {
        "id": 2,
        "image_url": "https://...",
        "link": "/vouchers",
        "sort_order": 2
      }
    ]
  }
}
```

---

## 4. Đơn hàng (Orders)

### 4.1 GET `/orders`

Danh sách đơn hàng của user.

**Input (Query params):**

| Param | Type   | Bắt buộc | Mô tả                                                        |
| ----- | ------ | --------- | ------------------------------------------------------------- |
| state | string | Không     | Lọc trạng thái: `pending`, `shipping`, `done`, `cancelled`   |
| page  | number | Không     | Trang (mặc định: 1)                                          |
| limit | number | Không     | Số đơn/trang (mặc định: 20)                                  |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "orders": [
      {
        "id": 501,
        "name": "SO/2026/0501",
        "state": "shipping",
        "date_order": "2026-04-10T14:30:00+07:00",
        "amount_total": 2580000,
        "items": [
          {
            "id": 1001,
            "product_name": "Máy khoan Bosch GSB 550",
            "product_image": "https://...",
            "quantity": 2,
            "price_unit": 1290000,
            "price_subtotal": 2580000
          }
        ]
      }
    ],
    "total": 12,
    "page": 1,
    "limit": 20
  }
}
```

---

### 4.2 GET `/orders/{id}`

Chi tiết 1 đơn hàng.

**Input (Path params):**

| Param | Type   | Bắt buộc | Mô tả      |
| ----- | ------ | --------- | ----------- |
| id    | number | Có        | ID đơn hàng |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "order": {
      "id": 501,
      "name": "SO/2026/0501",
      "state": "shipping",
      "date_order": "2026-04-10T14:30:00+07:00",
      "amount_total": 2580000,
      "amount_tax": 0,
      "shipping_fee": 0,
      "discount_amount": 0,
      "voucher_code": null,
      "shipping_address": {
        "name": "Nguyễn Văn A",
        "phone": "0901234567",
        "street": "123 Nguyễn Huệ",
        "ward": "Phường Bến Nghé",
        "district": "Quận 1",
        "city": "Thành phố Hồ Chí Minh"
      },
      "items": [
        {
          "id": 1001,
          "product_id": 101,
          "product_name": "Máy khoan Bosch GSB 550",
          "product_image": "https://...",
          "quantity": 2,
          "price_unit": 1290000,
          "price_subtotal": 2580000
        }
      ],
      "tracking_number": "VN123456789",
      "tracking_url": "https://tracking..."
    }
  }
}
```

---

### 4.3 POST `/orders`

Tạo đơn hàng mới.

**Input (Body):**

```json
{
  "address_id": 10,
  "voucher_code": "GIAM50K",
  "note": "Giao giờ hành chính",
  "items": [
    {
      "product_id": 101,
      "quantity": 2
    },
    {
      "product_id": 205,
      "quantity": 1
    }
  ]
}
```

| Field        | Type     | Bắt buộc | Mô tả                         |
| ------------ | -------- | --------- | ------------------------------ |
| address_id   | number   | Có        | ID địa chỉ giao hàng          |
| items        | array    | Có        | Danh sách sản phẩm + số lượng |
| voucher_code | string   | Không     | Mã voucher áp dụng            |
| note         | string   | Không     | Ghi chú giao hàng             |

**Output (201):**

```json
{
  "success": true,
  "data": {
    "order": {
      "id": 502,
      "name": "SO/2026/0502",
      "state": "pending",
      "date_order": "2026-04-15T10:00:00+07:00",
      "amount_total": 3870000,
      "items": [...]
    }
  }
}
```

---

## 5. Địa chỉ giao hàng (Addresses)

### 5.1 GET `/addresses`

Danh sách địa chỉ của user.

**Input:** _Không có_

**Output (200):**

```json
{
  "success": true,
  "data": {
    "addresses": [
      {
        "id": 10,
        "name": "Nguyễn Văn A",
        "phone": "0901234567",
        "street": "123 Nguyễn Huệ",
        "ward": "Phường Bến Nghé",
        "district": "Quận 1",
        "city": "Thành phố Hồ Chí Minh",
        "is_default": true
      }
    ]
  }
}
```

---

### 5.2 POST `/addresses`

Thêm địa chỉ mới.

**Input (Body):**

```json
{
  "name": "Nguyễn Văn A",
  "phone": "0901234567",
  "street": "456 Lê Lợi",
  "ward": "Phường Bến Thành",
  "district": "Quận 1",
  "city": "Thành phố Hồ Chí Minh",
  "is_default": false
}
```

| Field      | Type    | Bắt buộc | Mô tả                    |
| ---------- | ------- | --------- | ------------------------- |
| name       | string  | Có        | Tên người nhận            |
| phone      | string  | Có        | Số điện thoại             |
| street     | string  | Có        | Số nhà, tên đường         |
| ward       | string  | Có        | Phường / Xã               |
| district   | string  | Có        | Quận / Huyện              |
| city       | string  | Có        | Tỉnh / Thành phố          |
| is_default | boolean | Không     | Đặt làm mặc định (false)  |

**Output (201):**

```json
{
  "success": true,
  "data": {
    "address": {
      "id": 11,
      "name": "Nguyễn Văn A",
      "phone": "0901234567",
      "street": "456 Lê Lợi",
      "ward": "Phường Bến Thành",
      "district": "Quận 1",
      "city": "Thành phố Hồ Chí Minh",
      "is_default": false
    }
  }
}
```

---

### 5.3 PUT `/addresses/{id}`

Cập nhật địa chỉ.

**Input (Path + Body):**

- Path: `id` (number) — ID địa chỉ
- Body: Giống POST, chỉ gửi các field cần update

```json
{
  "street": "789 Hai Bà Trưng",
  "is_default": true
}
```

**Output (200):**

```json
{
  "success": true,
  "data": {
    "address": {
      "id": 11,
      "name": "Nguyễn Văn A",
      "phone": "0901234567",
      "street": "789 Hai Bà Trưng",
      "ward": "Phường Bến Thành",
      "district": "Quận 1",
      "city": "Thành phố Hồ Chí Minh",
      "is_default": true
    }
  }
}
```

---

### 5.4 DELETE `/addresses/{id}`

Xóa địa chỉ.

**Input (Path params):**

| Param | Type   | Bắt buộc | Mô tả      |
| ----- | ------ | --------- | ----------- |
| id    | number | Có        | ID địa chỉ  |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "deleted": true
  }
}
```

---

## 6. Loyalty / Membership

### 6.1 GET `/loyalty/tiers`

Danh sách hạng thành viên.

**Input:** _Không có_

**Output (200):**

```json
{
  "success": true,
  "data": {
    "tiers": [
      {
        "id": 1,
        "name": "Đồng",
        "min_points": 0,
        "max_points": 999,
        "color": "brown",
        "icon": "🥉",
        "description": "Hạng khởi đầu",
        "badge_color": "#CD7F32",
        "image_url": "https://...",
        "benefits": [
          { "id": 1, "name": "Tích 1 điểm / 10.000đ", "icon": "⭐" },
          { "id": 2, "name": "Voucher sinh nhật 50K", "icon": "🎂" }
        ]
      },
      {
        "id": 2,
        "name": "Bạc",
        "min_points": 1000,
        "max_points": 4999,
        "color": "silver",
        "icon": "🥈",
        "description": "Tích lũy từ 1,000 điểm",
        "badge_color": "#C0C0C0",
        "image_url": "https://...",
        "benefits": [
          { "id": 3, "name": "Tích 1.5 điểm / 10.000đ", "icon": "⭐" },
          { "id": 4, "name": "Free ship đơn từ 500K", "icon": "🚚" },
          { "id": 5, "name": "Voucher sinh nhật 100K", "icon": "🎂" }
        ]
      }
    ]
  }
}
```

---

### 6.2 GET `/loyalty/partner/lookup`

Tra cứu thông tin loyalty của user theo phone hoặc email.

**Input (Query params):**

| Param | Type   | Bắt buộc       | Mô tả         |
| ----- | ------ | --------------- | -------------- |
| phone | string | Có (hoặc email) | Số điện thoại  |
| email | string | Có (hoặc phone) | Email          |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "id": 123,
    "name": "Nguyễn Văn A",
    "phone": "0901234567",
    "email": "a@example.com",
    "total_points": 2500,
    "tier": {
      "id": 2,
      "name": "Bạc",
      "min_points": 1000,
      "max_points": 4999,
      "color": "silver",
      "icon": "🥈",
      "description": "Tích lũy từ 1,000 điểm",
      "badge_color": "#C0C0C0",
      "image_url": "https://...",
      "benefits": [...]
    },
    "vouchers": [],
    "recent_history": []
  }
}
```

---

### 6.3 GET `/loyalty/partner/{partner_id}`

Lấy đầy đủ thông tin loyalty của 1 partner.

**Input (Path params):**

| Param      | Type   | Bắt buộc | Mô tả      |
| ---------- | ------ | --------- | ----------- |
| partner_id | number | Có        | ID partner  |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "id": 123,
    "name": "Nguyễn Văn A",
    "phone": "0901234567",
    "email": "a@example.com",
    "total_points": 2500,
    "tier": { ... },
    "vouchers": [
      {
        "id": 301,
        "code": "HLV-A1B2C3",
        "state": "active",
        "discount_type": "fixed",
        "discount_value": 50000,
        "max_discount_amount": 50000,
        "min_order_amount": 500000,
        "apply_on": "all",
        "date_issued": "2026-04-01",
        "date_expiry": "2026-05-01",
        "package_name": "Giảm 50K"
      }
    ],
    "recent_history": [
      {
        "id": 401,
        "date": "2026-04-10T14:30:00+07:00",
        "point_amount": 129,
        "transaction_type": "earn",
        "description": "Mua hàng SO/2026/0501"
      }
    ]
  }
}
```

---

### 6.4 GET `/loyalty/partner/{partner_id}/history`

Lịch sử tích / tiêu điểm (phân trang).

**Input:**

| Param      | Vị trí | Type   | Bắt buộc | Mô tả                                           |
| ---------- | ------ | ------ | --------- | ------------------------------------------------ |
| partner_id | Path   | number | Có        | ID partner                                       |
| page       | Query  | number | Không     | Trang (mặc định: 1)                              |
| limit      | Query  | number | Không     | Số dòng/trang (mặc định: 20)                     |
| type       | Query  | string | Không     | Lọc: `earn`, `redeem`, `return`, `manual`         |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "history": [
      {
        "id": 401,
        "date": "2026-04-10T14:30:00+07:00",
        "point_amount": 129,
        "transaction_type": "earn",
        "description": "Mua hàng SO/2026/0501"
      },
      {
        "id": 400,
        "date": "2026-04-08T09:00:00+07:00",
        "point_amount": -500,
        "transaction_type": "redeem",
        "description": "Đổi voucher Giảm 50K"
      }
    ],
    "total": 45,
    "page": 1,
    "limit": 20
  }
}
```

---

### 6.5 GET `/loyalty/vouchers/{partner_id}`

Danh sách voucher của partner.

**Input:**

| Param      | Vị trí | Type   | Bắt buộc | Mô tả                                              |
| ---------- | ------ | ------ | --------- | --------------------------------------------------- |
| partner_id | Path   | number | Có        | ID partner                                          |
| state      | Query  | string | Không     | Lọc: `active`, `used`, `expired`, `cancelled`       |

**Output (200):**

```json
{
  "success": true,
  "data": {
    "vouchers": [
      {
        "id": 301,
        "code": "HLV-A1B2C3",
        "state": "active",
        "discount_type": "fixed",
        "discount_value": 50000,
        "max_discount_amount": 50000,
        "min_order_amount": 500000,
        "apply_on": "all",
        "date_issued": "2026-04-01",
        "date_expiry": "2026-05-01",
        "package_name": "Giảm 50K"
      }
    ]
  }
}
```

---

### 6.6 GET `/loyalty/voucher-packages`

Danh sách gói voucher có thể đổi điểm.

**Input:** _Không có_

**Output (200):**

```json
{
  "success": true,
  "data": {
    "packages": [
      {
        "id": 201,
        "name": "Giảm 50K",
        "points_required": 500,
        "discount_type": "fixed",
        "discount_value": 50000,
        "max_discount_amount": 50000,
        "validity_days": 30,
        "apply_on": "all",
        "min_order_amount": 500000
      },
      {
        "id": 202,
        "name": "Giảm 10%",
        "points_required": 800,
        "discount_type": "percent",
        "discount_value": 10,
        "max_discount_amount": 200000,
        "validity_days": 30,
        "apply_on": "all",
        "min_order_amount": 300000
      }
    ]
  }
}
```

---

### 6.7 POST `/loyalty/redeem`

Đổi điểm lấy voucher.

**Input (Body):**

```json
{
  "partner_id": 123,
  "package_id": 201
}
```

| Field      | Type   | Bắt buộc | Mô tả       |
| ---------- | ------ | --------- | ------------ |
| partner_id | number | Có        | ID partner   |
| package_id | number | Có        | ID gói voucher |

**Output (201):**

```json
{
  "success": true,
  "data": {
    "voucher": {
      "id": 302,
      "code": "HLV-X9Y8Z7",
      "state": "active",
      "discount_type": "fixed",
      "discount_value": 50000,
      "max_discount_amount": 50000,
      "min_order_amount": 500000,
      "apply_on": "all",
      "date_issued": "2026-04-15",
      "date_expiry": "2026-05-15",
      "package_name": "Giảm 50K"
    },
    "remaining_points": 2000
  }
}
```

**Output (400 — Không đủ điểm):**

```json
{
  "success": false,
  "error": {
    "code": "INSUFFICIENT_POINTS",
    "message": "Bạn cần 500 điểm, hiện có 300 điểm"
  }
}
```

---

### 6.8 POST `/loyalty/voucher/validate`

Kiểm tra mã voucher có hợp lệ không (khi checkout).

**Input (Body):**

```json
{
  "code": "HLV-A1B2C3",
  "order_amount": 1500000
}
```

| Field        | Type   | Bắt buộc | Mô tả                    |
| ------------ | ------ | --------- | ------------------------- |
| code         | string | Có        | Mã voucher                |
| order_amount | number | Không     | Giá trị đơn hàng (để check min_order) |

**Output (200 — Hợp lệ):**

```json
{
  "success": true,
  "data": {
    "valid": true,
    "voucher": {
      "id": 301,
      "code": "HLV-A1B2C3",
      "discount_type": "fixed",
      "discount_value": 50000,
      "max_discount_amount": 50000,
      "min_order_amount": 500000,
      "apply_on": "all",
      "date_expiry": "2026-05-01",
      "package_name": "Giảm 50K"
    },
    "discount_amount": 50000,
    "message": "Áp dụng thành công: Giảm 50,000đ"
  }
}
```

**Output (200 — Không hợp lệ):**

```json
{
  "success": true,
  "data": {
    "valid": false,
    "message": "Đơn hàng tối thiểu 500,000đ để sử dụng voucher này"
  }
}
```

---

### 6.9 POST `/loyalty/redeem/submit`

Lưu ý: `request_type="gift"` được xử lý ngay, trả về `state="done"` và `voucher_code`; không cần admin duyệt. Chỉ `request_type="cash"` ở trạng thái `pending` để admin xử lý.

Với đổi tiền mặt, request `pending` được tính vào `pending_reward_points`/điểm đang treo. Với đổi quà, điểm được trừ ngay và voucher được phát hành ngay.

**Input đổi tiền mặt:**

```json
{
  "partner_id": 123,
  "phone": "0901234567",
  "request_type": "cash",
  "points_to_redeem": 160,
  "bank_name": "Sacombank",
  "account_number": "040084366041",
  "account_name": "NGUYEN VAN A",
  "customer_note": "..."
}
```

**Output thành công:**

```json
{
  "success": true,
  "request_id": 55,
  "request_name": "RRQ/2026/0005",
  "request_type": "cash",
  "points_required": 160,
  "pending_reward_points": 160,
  "exchange_points_available": 0
}
```

**Output lỗi khi còn request treo:**

```json
{
  "error": "Không đủ điểm khả dụng. Cần 160 điểm, bạn còn 0 điểm. Đang treo 160 điểm trong yêu cầu chờ xử lý.",
  "code": "PENDING_REWARD_POINTS",
  "exchange_points": 160,
  "pending_reward_points": 160,
  "exchange_points_available": 0
}
```

Nếu không có điểm treo nhưng số dư thật không đủ, `code` là `INSUFFICIENT_POINTS`.

---

### 6.10 GET `/loyalty/redeem/requests`

Lấy danh sách yêu cầu đổi thưởng của partner.

**Query:** `partner_id=123&phone=0901234567&limit=50`

**Output:**

```json
{
  "success": true,
  "data": {
    "requests": [
      {
        "id": 55,
        "name": "RRQ/2026/0005",
        "request_type": "cash",
        "points_required": 160,
        "cash_value": 200000,
        "package_id": null,
        "package_name": "",
        "bank_name": "Sacombank",
        "account_number": "040084366041",
        "account_name": "NGUYEN VAN A",
        "state": "pending",
        "date_request": "2026-07-02T13:41:00+07:00",
        "date_done": null,
        "customer_note": "",
        "voucher_id": null,
        "voucher_code": ""
      }
    ],
    "exchange_points": 160,
    "pending_reward_points": 160,
    "exchange_points_available": 0
  }
}
```

---

### 6.11 POST `/loyalty/redeem/cancel`

Hủy yêu cầu đổi thưởng đang `pending` để giải phóng điểm đang treo.

**Input:**

```json
{
  "partner_id": 123,
  "phone": "0901234567",
  "request_id": 55
}
```

Có thể gọi path thay thế: `POST /loyalty/redeem/requests/{request_id}/cancel`.

**Output thành công:**

```json
{
  "success": true,
  "data": {
    "request": {
      "id": 55,
      "name": "RRQ/2026/0005",
      "state": "cancelled",
      "points_required": 160
    },
    "pending_reward_points": 0,
    "exchange_points_available": 160
  }
}
```

**Lỗi chính:** `REQUEST_NOT_FOUND`, `REQUEST_NOT_PENDING`.

---

## Tổng hợp Endpoints

| #  | Method | Endpoint                              | Mô tả                        |
| -- | ------ | ------------------------------------- | ----------------------------- |
| 1  | POST   | `/auth/zalo`                          | Xác thực Zalo → API key       |
| 2  | GET    | `/categories`                         | Danh sách danh mục            |
| 3  | GET    | `/products`                           | Danh sách sản phẩm            |
| 4  | GET    | `/products/{id}`                      | Chi tiết sản phẩm             |
| 5  | GET    | `/banners`                            | Banner quảng cáo              |
| 6  | GET    | `/orders`                             | Danh sách đơn hàng            |
| 7  | GET    | `/orders/{id}`                        | Chi tiết đơn hàng             |
| 8  | POST   | `/orders`                             | Tạo đơn hàng                  |
| 9  | GET    | `/addresses`                          | Danh sách địa chỉ             |
| 10 | POST   | `/addresses`                          | Thêm địa chỉ                  |
| 11 | PUT    | `/addresses/{id}`                     | Cập nhật địa chỉ              |
| 12 | DELETE | `/addresses/{id}`                     | Xóa địa chỉ                   |
| 13 | GET    | `/loyalty/tiers`                      | Danh sách hạng thành viên     |
| 14 | GET    | `/loyalty/partner/lookup`             | Tra cứu loyalty theo phone    |
| 15 | GET    | `/loyalty/partner/{id}`               | Thông tin loyalty partner     |
| 16 | GET    | `/loyalty/partner/{id}/history`       | Lịch sử tích điểm            |
| 17 | GET    | `/loyalty/vouchers/{partner_id}`      | Voucher của partner           |
| 18 | GET    | `/loyalty/voucher-packages`           | Gói voucher khả dụng          |
| 19 | POST   | `/loyalty/redeem`                     | Đổi điểm lấy voucher          |
| 20 | POST   | `/loyalty/voucher/validate`           | Kiểm tra mã voucher           |
| 21 | POST   | `/loyalty/redeem/submit`              | Gửi yêu cầu đổi thưởng        |
| 22 | GET    | `/loyalty/redeem/requests`            | Danh sách yêu cầu đổi thưởng  |
| 23 | POST   | `/loyalty/redeem/cancel`              | Hủy yêu cầu đổi thưởng pending |

> **Tỉnh/Thành phố, Quận/Huyện, Phường/Xã**: Sử dụng API miễn phí `https://provinces.open-api.vn/api/` — KHÔNG cần expose từ Odoo.
