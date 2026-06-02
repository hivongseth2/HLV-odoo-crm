# HLV Invoice Guard API

Module này expose API đọc `sale.order` và `purchase.order` liên kết qua:

```text
purchase.order.origin = sale.order.name
```

Routes:

```text
GET/POST /api/hlv/invoice_guard/sale
POST     /api/hlv/invoice_guard/check
```

Payload tối thiểu:

```json
{
  "token": "your-token",
  "sale_name": "SO00123"
}
```

Route `/check` nhận thêm `lines` từ grid AMIS và trả về danh sách lệch VAT, giá, số lượng.
