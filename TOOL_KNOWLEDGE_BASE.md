# Hướng dẫn sử dụng Công cụ AI (LLM Tools)

Tài liệu này mô tả tất cả công cụ AI có sẵn trong hệ thống. Khi người dùng yêu cầu thao tác liên quan, hãy chọn đúng tool và truyền đúng tham số.

---

## 1. MISA CRM — Sản phẩm

### 1.1 search_product_misa — Tìm sản phẩm trên MISA

Tìm kiếm sản phẩm trong hệ thống **MISA CRM** theo tên hoặc mã. Dùng để kiểm tra sản phẩm đã tồn tại trước khi tạo mới.

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `name` | string | ✅ | Tên hoặc từ khóa sản phẩm (VD: `Khoan FPD3`, `Bulong M12`) |

**Khi nào dùng:**
- Người dùng hỏi "tìm sản phẩm X trên MISA"
- Trước khi tạo sản phẩm mới, LUÔN tìm trước để kiểm tra trùng
- Khi cần lấy `misa_id` để cập nhật sản phẩm

**Ví dụ gọi:**
```json
{"name": "Khoan Bosch FPD3"}
```

**Kết quả trả về:** Danh sách sản phẩm gồm `misa_id`, `code`, `name`, `price`, `cost`, `unit`, `category`, `tax`, `type`, `active`.

---

### 1.2 create_product_misa — Tạo sản phẩm mới trên MISA

Tạo sản phẩm mới vào hệ thống MISA CRM. Đồng bộ tự động sang Odoo.

⚠️ **CHỈ GỌI KHI NGƯỜI DÙNG ĐÃ XÁC NHẬN "OK" HOẶC "ĐỒNG Ý".**

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `code` | string | ✅ | Mã sản phẩm (viết liền, in hoa, không dấu). VD: `KHOANFPD3` |
| `name` | string | ✅ | Tên sản phẩm chuẩn hóa đầy đủ. VD: `Khoan Bosch FPD3 850W` |
| `price` | number | ✅ | Giá bán đề xuất (VNĐ). VD: `1500000` |
| `price_pu` | number | ✅ | Giá mua (VNĐ). VD: `1200000` |
| `tax` | number | ✅ | Thuế VAT (%). Thường là `8` hoặc `10` |
| `unit` | string | ✅ | Đơn vị tính: `Cái`, `Bộ`, `Hộp`, `Chai`, `Cuộn`... |
| `category` | string | ✅ | Tên nhóm hàng (lấy từ danh mục MISA) |
| `category_id` | integer | ✅ | ID nhóm hàng (tra từ danh mục MISA) |
| `type` | string | ✅ | Loại: `goods` (hàng hóa), `service` (dịch vụ), `finished_product` (thành phẩm) |

**Quy trình chuẩn:**
1. Dùng `search_product_misa` kiểm tra sản phẩm đã tồn tại chưa
2. Nếu chưa có → đề xuất thông tin cho người dùng xác nhận
3. Người dùng xác nhận → gọi `create_product_misa`
4. Nếu không biết `category_id` → dùng `search_category_misa` để tìm

**Ví dụ gọi:**
```json
{
  "code": "KHOANFPD3",
  "name": "Khoan Bosch FPD3 850W",
  "price": 1500000,
  "price_pu": 1200000,
  "tax": 10,
  "unit": "Cái",
  "category": "Máy Milwaukee",
  "category_id": 166,
  "type": "goods"
}
```

---

### 1.3 update_product_misa — Cập nhật thông tin sản phẩm trên MISA

Cập nhật một trường cụ thể của sản phẩm trên MISA. Cần có `misa_id` (lấy từ kết quả `search_product_misa`).

⚠️ **Yêu cầu xác nhận từ người dùng trước khi cập nhật.**

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `misa_id` | string | ✅ | MISA product ID (lấy từ search). VD: `74519` |
| `field` | string | ✅ | Trường cần cập nhật (xem bảng bên dưới) |
| `new_value` | string | ✅ | Giá trị mới |
| `old_value` | string | ✅ | Giá trị cũ (để đối chứng) |

**Các trường hỗ trợ (field):**

| Giá trị `field` | Tên trường MISA | Mô tả | VD `new_value` |
|------------------|-----------------|-------|-----------------|
| `name` | ProductName | Tên sản phẩm | `Khoan Bosch FPD3 850W` |
| `code` | ProductCode | Mã sản phẩm | `KHOANFPD3` |
| `unit_price_fixed` | UnitPriceFixed | Đơn giá bán cố định | `1500000` |
| `purchased_price` | PurchasedPrice | Đơn giá mua | `1200000` |
| `unit_price` | UnitPrice | Đơn giá bán lẻ (gồm VAT) | `1650000` |
| `tax` | TaxID | Thuế GTGT (truyền % không phải ID) | `10` hoặc `8` |
| `custom_field_16` | CustomField16 | Đơn giá mua bắt buộc | `1200000` |



**Ví dụ — Cập nhật giá bán:**
```json
{
  "misa_id": "74519",
  "field": "unit_price",
  "new_value": "1000000",
  "old_value": "5000"
}
```

**Ví dụ — Cập nhật thuế:**
```json
{
  "misa_id": "74519",
  "field": "tax",
  "new_value": "10",
  "old_value": "8"
}
```

**Ví dụ — Cập nhật giá bán cố định:**
```json
{
  "misa_id": "74519",
  "field": "unit_price_fixed",
  "new_value": "1500000",
  "old_value": "1200000"
}
```

**Ví dụ — Cập nhật giá mua:**
```json
{
  "misa_id": "74519",
  "field": "purchased_price",
  "new_value": "900000",
  "old_value": "800000"
}
```

**Quy trình chuẩn:**
1. Dùng `search_product_misa` để lấy `misa_id` và giá trị hiện tại
2. Xác nhận với người dùng giá trị cũ/mới
3. Gọi `update_product_misa` với đúng `field`, `new_value`, `old_value`
4. Mỗi lần chỉ cập nhật MỘT trường. Muốn cập nhật nhiều trường → gọi nhiều lần.

---

## 2. MISA CRM — Nhóm sản phẩm

### 2.1 get_category_info — Lấy tên nhóm sản phẩm từ ID

Kiểm tra tên chính xác của nhóm sản phẩm bằng ID trên MISA.

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `category_id` | string | ✅ | ID nhóm sản phẩm. VD: `52`, `166` |

**Khi nào dùng:**
- Double-check ID nhóm trước khi tạo sản phẩm
- Xác nhận nhóm hàng đúng không

**Ví dụ gọi:**
```json
{"category_id": "166"}
```

---

### 2.2 search_category_misa — Tìm nhóm sản phẩm theo tên

Tìm kiếm ID nhóm sản phẩm theo tên trên MISA CRM.

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `name` | string | ✅ | Tên nhóm cần tìm. VD: `Vật tư khí nén`, `Bảo hộ lao động`, `Máy Milwaukee` |

**Khi nào dùng:**
- Người dùng yêu cầu tạo SP thuộc nhóm cụ thể nhưng không biết ID
- Cần tra cứu `category_id` để truyền vào `create_product_misa`

**Ví dụ gọi:**
```json
{"name": "Máy Milwaukee"}
```

---

## 3. MISA CRM — Chứng từ mua hàng

### 3.1 search_purchase_voucher — Tìm chứng từ nhập kho

Tìm kiếm chứng từ nhập kho mua hàng trong MISA theo diễn giải hoặc mã.

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `journal_memo` | string | ✅ | Diễn giải hoặc mã chứng từ. VD: `DH1255`, `PO0012` |
| `limit` | integer | ❌ | Số kết quả tối đa (mặc định 20) |

**Khi nào dùng:**
- Người dùng hỏi "tìm đơn hàng DH1255"
- Hỗ trợ tìm nhiều mã cùng lúc, phân cách bằng dấu phẩy: `DH1255, DH1256`

**Ví dụ gọi:**
```json
{"journal_memo": "DH1255, DH1256", "limit": 10}
```

---

## 4. Zalo — Tồn kho & Sản phẩm

### 4.1 zalo_check_stock — Kiểm tra tồn kho theo kho

Kiểm tra tồn kho sản phẩm chi tiết theo từng kho (warehouse) trong Odoo.

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `product` | string | ✅ | Mã SP (VD: `FPD3-01`) hoặc tên SP (VD: `Khoan Bosch`) |

**Khi nào dùng:**
- Khách hỏi "còn hàng không?", "tồn bao nhiêu?", "check tồn giúp em"
- Cần biết tồn kho CỤ THỂ theo từng kho (HLV, WH1, WH2...)

**Kết quả trả về:** Tồn kho thực tế (`qty_available`), dự kiến (`virtual_available`), chi tiết theo từng mã kho.

**Ví dụ gọi:**
```json
{"product": "FPD3-01"}
```

**So sánh với search_product_misa:** Tool này tìm trong **Odoo** (tồn kho thực), còn `search_product_misa` tìm trong **MISA** (danh mục SP).

---

### 4.2 zalo_search_product_odoo — Tìm sản phẩm trong Odoo

Tìm kiếm sản phẩm thông minh trong Odoo bằng nhiều phương pháp: alias, vector similarity, text search.

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `name` | string | ✅ | Tên hoặc mã sản phẩm cần tìm |

**Khi nào dùng:**
- Cần lấy `product ID` trong Odoo để tạo báo giá
- So sánh giá/tồn kho giữa các SP
- Tìm SP bằng tên không chính xác (fuzzy search qua vector)

**Kết quả trả về:** `id`, `name`, `code`, `price`, `category`, `unit`, `qty_available`, `stock_by_warehouse`.

**Ví dụ gọi:**
```json
{"name": "máy khoan bosch"}
```

---

## 5. Zalo — Hội thoại

### 5.1 zalo_summarize_conversation — Tóm tắt hội thoại Zalo

Dùng AI tóm tắt nội dung hội thoại Zalo: nhu cầu khách, SP quan tâm, thái độ, trạng thái.

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `conversation_id` | integer | ✅ | ID hội thoại (bảng `zalo.chat.conversation`) |

**Khi nào dùng:**
- Sale cần nắm nhanh bối cảnh hội thoại
- Người dùng hỏi "tóm tắt cuộc chat với khách X"

**Kết quả trả về:** `conversation_id`, `customer` (tên khách), `summary` (tóm tắt bằng tiếng Việt).

**Ví dụ gọi:**
```json
{"conversation_id": 42}
```

---

## 6. Zalo — Bán hàng

### 6.1 zalo_create_quote — Tạo báo giá (Sale Order)

Tạo báo giá trong Odoo từ danh sách sản phẩm. Tự động tìm SP theo tên/mã.

⚠️ **CHỈ GỌI KHI NGƯỜI DÙNG XÁC NHẬN muốn tạo báo giá.**

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `partner_id` | integer | ✅ | ID khách hàng (`res.partner`) |
| `products` | string | ✅ | JSON array sản phẩm (xem format bên dưới) |
| `note` | string | ❌ | Ghi chú cho báo giá |

**Format `products`:**
```json
[
  {"name": "Khoan FPD3", "quantity": 2, "price_unit": 500000},
  {"name": "Bulong M12", "quantity": 100, "price_unit": 0}
]
```
- `name`: tên hoặc mã SP — hệ thống tự tìm trong Odoo
- `quantity`: số lượng (mặc định 1)
- `price_unit`: giá bán — `0` = lấy bảng giá mặc định

**Quy trình chuẩn:**
1. Xác định khách hàng (`partner_id`)
2. Liệt kê SP + SL + giá cho người dùng xác nhận
3. Người dùng OK → gọi `zalo_create_quote`

**Ví dụ gọi:**
```json
{
  "partner_id": 15,
  "products": "[{\"name\": \"Khoan FPD3\", \"quantity\": 2, \"price_unit\": 500000}]",
  "note": "Đơn hàng từ Zalo chat"
}
```

---

### 6.2 zalo_send_message — Gửi tin nhắn Zalo

Gửi tin nhắn văn bản tới khách hàng qua Zalo OA. Tin nhắn sẽ được gửi **thật** tới Zalo của khách.

⚠️ **CHỈ GỌI KHI NGƯỜI DÙNG XÁC NHẬN muốn gửi. Tin nhắn gửi đi KHÔNG THỂ thu hồi.**

**Tham số:**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `conversation_id` | integer | ✅ | ID hội thoại (`zalo.chat.conversation`) |
| `message` | string | ✅ | Nội dung tin nhắn (text thuần, không HTML) |

**Khi nào dùng:**
- Người dùng yêu cầu gửi tin nhắn cho khách qua Zalo
- Soạn tin trả lời tự động cho khách

**Ví dụ gọi:**
```json
{
  "conversation_id": 42,
  "message": "Chào anh/chị, sản phẩm Khoan FPD3 hiện còn 5 cái trong kho. Giá 1,500,000đ. Anh/chị muốn đặt bao nhiêu ạ?"
}
```

---

## Bảng tổng hợp tất cả Tools

| # | Tool | Hệ thống | Loại | Cần xác nhận |
|---|------|----------|------|--------------|
| 1 | `search_product_misa` | MISA | Đọc | Không |
| 2 | `create_product_misa` | MISA | Ghi | **Có** |
| 3 | `update_product_misa` | MISA | Ghi | **Có** |
| 4 | `get_category_info` | MISA | Đọc | Không |
| 5 | `search_category_misa` | MISA | Đọc | Không |
| 6 | `search_purchase_voucher` | MISA | Đọc | Không |
| 7 | `zalo_check_stock` | Odoo | Đọc | Không |
| 8 | `zalo_search_product_odoo` | Odoo | Đọc | Không |
| 9 | `zalo_summarize_conversation` | Zalo/AI | Đọc | Không |
| 10 | `zalo_create_quote` | Odoo | Ghi | **Có** |
| 11 | `zalo_send_message` | Zalo | Ghi | **Có** |

---

## Quy tắc chung khi sử dụng Tools

1. **Luôn tìm trước khi tạo**: Dùng `search_product_misa` hoặc `zalo_search_product_odoo` kiểm tra SP đã tồn tại chưa trước khi gọi `create_product_misa`.

2. **Xác nhận trước khi ghi**: Các tool có đánh dấu "Cần xác nhận" (`create`, `update`, `send`) — PHẢI hỏi người dùng xác nhận trước khi gọi.

3. **Phân biệt MISA vs Odoo**:
   - `search_product_misa` → tìm trên **MISA CRM** (hệ thống kế toán, quản lý danh mục SP)
   - `zalo_search_product_odoo` / `zalo_check_stock` → tìm/check tồn trên **Odoo** (hệ thống kho, bán hàng)
   - Khi tạo SP mới trên MISA (`create_product_misa`), hệ thống tự đồng bộ sang Odoo.

4. **Cập nhật sản phẩm**: `update_product_misa` chỉ cập nhật MỘT trường mỗi lần. Muốn cập nhật nhiều trường (VD: giá bán + giá mua + thuế) → gọi tool 3 lần riêng biệt.

5. **Thuế**: Khi cập nhật thuế qua `update_product_misa`, truyền **phần trăm** (VD: `"10"`, `"8"`, `"0"`), KHÔNG truyền MISA tax ID. Hệ thống tự chuyển đổi.

6. **Giá**: Tất cả giá tính bằng VNĐ, không có phần thập phân. VD: `1500000` (không phải `1,500,000` hay `1.500.000`).

7. **Báo giá**: `zalo_create_quote` tự tìm SP theo tên/mã trong Odoo. Nếu SP không tìm thấy, sẽ thêm dòng ghi chú thay vì lỗi.

8. **Gửi tin Zalo**: `zalo_send_message` gửi **thật** qua Zalo API. Tin nhắn không thể thu hồi. Luôn cho người dùng xem nội dung tin nhắn trước khi gửi.
