# API MISA CRM của Odoo HLV

Odoo đăng nhập MISA CRM thay bên gọi. Bên gọi chỉ cần **API key**, không cầm tài khoản hay token MISA.

## Bật

Cài đặt → Tồn kho → khối **API MISA CRM cho bên ngoài**:

1. Bật **Bật API MISA CRM** → Lưu.
2. Bấm **Tạo key mới** → copy key gửi bên gọi.
3. Muốn cho tạo cơ hội thì bật thêm **Cho phép tạo dữ liệu trên MISA**.

Tắt API = mọi route trả 503, kể cả key đúng.

## Gọi

- Mọi route: `POST`, body JSON, header `X-API-Key: <key>`, `Content-Type: application/json`.
- Route không có tham số gửi body rỗng hoặc `{}`.
- Kết quả luôn có `ok`. Lỗi: `{"ok": false, "error": "<mã>", "message": "<câu đọc được>"}`.

| HTTP | `error` | Khi nào |
|---|---|---|
| 400 | `missing_field`, `invalid_field`, `invalid_json`, `invalid_stage`, `invalid_lead_source`, `combo_not_supported` | Body thiếu / sai |
| 401 | `missing_key` | Không có header X-API-Key |
| 403 | `invalid_key`, `write_disabled` | Sai key / route tạo mà chưa cho ghi |
| 404 | `not_found`, `product_not_found` | Không có khách / mã hàng trên MISA |
| 502 | `misa_error` | MISA lỗi hoặc từ chối (xem `message`) |
| 503 | `disabled`, `not_configured` | API đang tắt / chưa tạo key |

```bash
curl -X POST https://<odoo>/api/misa-crm/product/search \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"keyword": "4530", "in_stock_only": true}'
```

## Route

`page` bắt đầu từ 1; `limit` mặc định 10, tối đa 100.

### Chung
| Route | Body | Trả |
|---|---|---|
| `/api/misa-crm/ping` | — | `write_enabled`. Không gọi MISA — để thử key. |

### Khách hàng
| Route | Body | Trả |
|---|---|---|
| `/api/misa-crm/account/search` | `keyword` (tên / MST / mã KH / SĐT / địa chỉ, kiểu "chứa"), `page`, `limit` | `items[]`: `id, name, code, tax_code, phone, email, billing_address, shipping_address, owner_id, debt, debt_limit` |
| `/api/misa-crm/account/get` | `id` | `account` (như trên) |

### Hàng hóa
| Route | Body | Trả |
|---|---|---|
| `/api/misa-crm/product/search` | `keyword` (mã / tên), `page`, `limit`, `in_stock_only` | `items[]`: `id, code, name, unit_id, unit, tax_id, tax, tax_percent, price, is_combo, category, description, stock, owner_id` (+ `stock_qty` khi `in_stock_only`), `total` |
| `/api/misa-crm/product/prices` | `product_ids` [ID MISA], `account_id` (tuỳ chọn) | `products[]`, `price_book`, `recent_prices` (hai phần sau để nguyên như MISA trả) |

`in_stock_only: true` giống popup "Chọn hàng hóa": chỉ hàng còn tồn, không combo, không ngừng dùng. Không bật thì giống ô mã hàng trên dòng: mọi hàng.

### Cơ hội
| Route | Body | Trả |
|---|---|---|
| `/api/misa-crm/opportunity/options` | — | `stages[]` (`id, name, probability`), `lead_sources[]` (`id, name`) |
| `/api/misa-crm/opportunity/search` | `keyword` (bắt buộc), `limit` | `items[]`: `id, code, name, account, owner, stage, closing_date, products` |
| `/api/misa-crm/opportunity/lines` | `id` | `items[]`: `code, description, unit, qty, price, price_after_tax, tax, is_combo` |
| `/api/misa-crm/opportunity/create` | xem dưới | `id, code, total` (+ `warning`) |

Tạo cơ hội (cần bật **Cho phép tạo dữ liệu**):

```json
{
  "account_id": 4371,
  "closing_date": "2026-11-01",
  "stage_id": 1,
  "lead_source_id": 6,
  "name": "Bán hàng cho BOSCH",
  "description": "Khách hỏi qua Zalo",
  "lines": [
    {"code": "48-22-4530", "qty": 2, "price_after_tax": 380000},
    {"code": "AK-3572", "qty": 1, "price": 833333.33, "description": "Giao trước 20/11"}
  ]
}
```

- Bắt buộc: `account_id`, `closing_date`. `stage_id` mặc định 1 ("Nhận yêu cầu mua hàng"). `name` mặc định "Bán hàng cho <tên khách>".
- Mỗi dòng gửi **một** trong hai giá: `price_after_tax` (đơn giá sau VAT, nên dùng) hoặc `price` (chưa VAT). Thuế suất, đơn vị tính lấy theo hàng trên MISA.
- Mã hàng phải đúng tuyệt đối (không phân biệt hoa thường). Combo chưa hỗ trợ (400).
- Mọi tham chiếu được kiểm trước; sai một cái là **không tạo gì**.
- Người phụ trách = tài khoản MISA của Odoo.
- **Không chống trùng**: gọi lại sau khi đã tạo xong là thêm một cơ hội nữa. Có `id` trả về là đã tạo, kể cả khi kèm `warning`.

### Báo giá, đơn hàng
| Route | Body | Trả |
|---|---|---|
| `/api/misa-crm/quote/search` | `keyword` (bắt buộc), `limit` | `items[]`: `id, code, date, account_id, account, total, stage, owner` |
| `/api/misa-crm/quote/lines` | `id` | `items[]`: `code, name, note, unit, qty, price, tax_percent, is_combo` |
| `/api/misa-crm/sale-order/search` | `keyword` (bắt buộc), `limit` | `items[]`: `id, code, name, date, amount, account_id, account, owner, revenue_status, delivery_status, pay_status, quote, opportunity` |
| `/api/misa-crm/sale-order/lines` | `id` | `items[]`: `code, description, unit, qty, price, price_after_tax, tax_percent, discount, total, is_combo` |

## Chưa có

Thêm khách hàng, tạo báo giá, tạo đơn hàng: chưa có request mẫu của MISA nên chưa làm (không đoán body ghi dữ liệu thật).
