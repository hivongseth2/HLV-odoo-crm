# MISA Purchase Order Sync API

## Endpoint
```
POST /api/misa/purchase_order/sync
```

## Authentication
- **Type**: Token-based
- **Header**: `X-MISA-Token: hoanglongvu` (hoặc trong body)
- **Config**: Có thể thay đổi token qua System Parameters `misa.api.token`

## Request Body (JSON)

```json
{
  "token": "hoanglongvu",
  "po_code": "DMH12218",
  "create_when_missing": true
}
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `token` | string | Yes | - | Token xác thực (hoặc gửi qua header `X-MISA-Token`) |
| `po_code` | string | Yes | - | Mã đơn hàng cần đồng bộ (ví dụ: DMH12218) |
| `create_when_missing` | boolean | No | `true` | Có tạo đơn mới trong Odoo nếu chưa tồn tại |

## Response

### Success Response (200 OK)

#### Trường hợp 1: Cập nhật đơn đã có
```json
{
  "ok": true,
  "res_id": 123,
  "name": "DMH12218",
  "action": "updated",
  "detail": "Đã cập nhật đơn DMH12218 từ MISA"
}
```

#### Trường hợp 2: Tạo đơn mới
```json
{
  "ok": true,
  "res_id": 124,
  "name": "DMH12218",
  "action": "created",
  "detail": "Đã tạo mới đơn DMH12218 từ MISA"
}
```

#### Trường hợp 3: Đơn chỉ có trong Odoo (không còn trong MISA)
```json
{
  "ok": true,
  "res_id": 125,
  "name": "DMH12218",
  "action": "orphaned",
  "detail": "Đơn DMH12218 tồn tại trong Odoo nhưng không còn trong MISA"
}
```

#### Trường hợp 4: Không tìm thấy trong MISA
```json
{
  "ok": false,
  "res_id": null,
  "name": null,
  "action": "not_found",
  "detail": "Không tìm thấy đơn DMH12218 trong MISA"
}
```

### Error Response

#### Token không hợp lệ
```json
{
  "ok": false,
  "error": "invalid_token",
  "message": "Token không hợp lệ."
}
```

#### Thiếu mã đơn
```json
{
  "ok": false,
  "error": "missing_po_code",
  "message": "Thiếu mã đơn hàng (po_code)"
}
```

#### Lỗi xử lý
```json
{
  "ok": false,
  "error": "create_failed",
  "message": "Chi tiết lỗi..."
}
```

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `ok` | boolean | Trạng thái thành công/thất bại |
| `res_id` | integer or null | ID của đơn hàng trong Odoo |
| `name` | string or null | Tên/mã đơn hàng |
| `action` | string | Hành động đã thực hiện: `created`, `updated`, `deleted`, `not_found`, `orphaned` |
| `detail` | string | Chi tiết kết quả |
| `error` | string | (Chỉ khi lỗi) Mã lỗi |
| `message` | string | (Chỉ khi lỗi) Thông báo lỗi |

## Sync Logic

API thực hiện đồng bộ theo logic sau:

1. **Tìm trong MISA**: Gọi API MISA để tìm đơn theo `po_code`
2. **Tìm trong Odoo**: Tìm đơn theo `name` hoặc `origin` = `po_code`
3. **Xử lý theo trường hợp**:
   - Có cả 2 → **CẬP NHẬT** đơn trong Odoo theo MISA
   - Chỉ có MISA + `create_when_missing=true` → **TẠO MỚI** đơn trong Odoo
   - Chỉ có MISA + `create_when_missing=false` → Trả về `not_found`
   - Chỉ có Odoo → Báo cáo `orphaned` (không xóa tự động)
   - Không có đâu → Trả về `not_found`

## Examples

### cURL Example
```bash
curl -X POST https://your-odoo-domain.com/api/misa/purchase_order/sync \
  -H "Content-Type: application/json" \
  -H "X-MISA-Token: hoanglongvu" \
  -d '{
    "po_code": "DMH12218",
    "create_when_missing": true
  }'
```

### Python Example
```python
import requests

url = "https://your-odoo-domain.com/api/misa/purchase_order/sync"
headers = {
    "Content-Type": "application/json",
    "X-MISA-Token": "hoanglongvu"
}
payload = {
    "po_code": "DMH12218",
    "create_when_missing": True
}

response = requests.post(url, json=payload, headers=headers)
result = response.json()

if result.get("ok"):
    print(f"Success: {result['action']} - {result['detail']}")
else:
    print(f"Error: {result.get('message')}")
```

### JavaScript/Node.js Example
```javascript
const axios = require('axios');

const url = 'https://your-odoo-domain.com/api/misa/purchase_order/sync';
const headers = {
  'Content-Type': 'application/json',
  'X-MISA-Token': 'hoanglongvu'
};
const payload = {
  po_code: 'DMH12218',
  create_when_missing: true
};

axios.post(url, payload, { headers })
  .then(response => {
    const result = response.data;
    if (result.ok) {
      console.log(`Success: ${result.action} - ${result.detail}`);
    } else {
      console.log(`Error: ${result.message}`);
    }
  })
  .catch(error => {
    console.error('Request failed:', error);
  });
```

## Notes

- API không yêu cầu login Odoo (auth='none'), sử dụng token riêng
- API chạy với quyền admin để truy cập đầy đủ dữ liệu
- Khi `action="orphaned"`, đơn vẫn tồn tại trong Odoo nhưng không có trong MISA (cần xem xét xóa thủ công)
- Token có thể cấu hình qua System Parameters: `misa.api.token`
