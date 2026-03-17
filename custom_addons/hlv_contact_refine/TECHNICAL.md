# Technical Documentation - hlv_contact_refine Module

## 1. Mục đích Module (Purpose)

Module `hlv_contact_refine` phục vụ 3 mục đích chính:

1. **Lọc giao diện Contact**: Ẩn các địa chỉ giao hàng (child contacts/delivery addresses) mặc định, giúp giao diện Contacts trở nên gọn gàng hơn.
2. **Tự động phân loại**: Tự động gắn tag (Khách hàng, Nhà cung cấp, Liên hệ chính, Địa chỉ giao hàng) dựa trên dữ liệu thực tế (sale orders, purchase orders).
3. **Đồng bộ MISA**: Cập nhật thông tin thuế & mã số thuế từ MISA ERP.

---

## 2. Cấu trúc thư mục (Directory Structure)

```
hlv_contact_refine/
├── __init__.py
├── __manifest__.py
├── data/
│   ├── filter_tag_data.xml        # Dữ liệu tag phân loại mặc định
│   └── ir_actions_server.xml      # Server actions & Menu items
├── models/
│   ├── __init__.py
│   ├── contact_filter_tag.py       # Model lưu tag phân loại
│   ├── hlv_contact_misa_sync.py    # Logic đồng bộ MISA API
│   └── res_partner.py              # Mở rộng res.partner
├── security/
│   └── ir.model.access.csv         # Phân quyền truy cập
└── views/
    └── res_partner_views.xml       # Views & Filters
```

---

## 3. Mô tả chi tiết từng thành phần

### 3.1. Models

#### 3.1.1. `contact_filter_tag.py`
- **Model**: `hlv.contact.filter.tag`
- **Mục đích**: Lưu trữ các tag phân loại liên hệ
- **Fields**:
  - `name`: Tên tag (dịch được - translate=True)
  - `code`: Mã code nội bộ
  - `sequence`: Thứ tự hiển thị

#### 3.1.2. `res_partner.py`
- **Inherit**: `res.partner`
- **Mục đích**: Thêm các computed fields để phân loại và lọc contacts
- **Fields**:
  - `child_contact_count`: Số lượng liên hệ con (delivery addresses)
  - `hlv_filter_tag_ids`: Tags phân loại (stored, compute)
  - `hlv_partner_type`: Loại liên hệ (Công ty / Cá nhân)
- **Logic tự động gắn tag**:
  - **Customer Tag**: Gắn nếu `customer_rank > 0` HOẶC có Sale Order
  - **Vendor Tag**: Gắn nếu `supplier_rank > 0` HOẶC có Purchase Order
  - **Main Contact Tag**: Gắn nếu `parent_id = False` (không có parent)
  - **Delivery Tag**: Gắn nếu `type = 'delivery'`

#### 3.1.3. `hlv_contact_misa_sync.py`
- **Inherit**: `res.partner`
- **Mục đích**: Đồng bộ thông tin thuế từ MISA ERP
- **Method chính**: `action_misa_update_bulk()`
  - **Input**: Không cần (quét toàn bộ)
  - **Logic**:
    1. Gọi MISA API lấy danh sách Customer & Vendor
    2. Match theo `account_object_code` → `company_registry`
    3. Nếu không match, fallback sang match theo `account_object_name` → `name`
    4. Update: `vat` (company_tax_code), `company_registry` (account_object_code)
  - **Dependencies**: `misa_api_utils`, `misa_config` (từ module `misa_fetch_po_button`)

---

### 3.2. Data Files

#### 3.2.1. `filter_tag_data.xml`
- Tạo 4 tags mặc định:
  1. `tag_customer`: "Khách hàng" (sequence=10)
  2. `tag_vendor`: "Nhà cung cấp" (sequence=20)
  3. `tag_main`: "Liên hệ chính" (sequence=30)
  4. `tag_delivery`: "Địa chỉ giao hàng" (sequence=40)

#### 3.2.2. `ir_actions_server.xml`
- **Action 1**: `action_convert_to_company` - "Cập nhật thành Công ty (Quét tự động)"
  - Tìm các contact có tên chứa keyword (công ty, cty, doanh nghiệp, tnhh, etc.)
  - Chuyển `is_company = True`
  - Trigger recompute tag
  - Menu: Configuration > Quét & Chuyển đổi Công ty

- **Action 2**: `action_misa_contact_bulk_sync` - "Cập nhật thông tin từ MISA"
  - Gọi `action_misa_update_bulk()` trong `res.partner`
  - Menu: Configuration > Cập nhật thông tin từ MISA

---

### 3.3. Views

#### 3.3.1. `res_partner_views.xml`
- **Filter**: Thêm các bộ lọc trong Search view
  - "Liên hệ chính": Chỉ hiển thị `parent_id = False`
  - "Địa chỉ giao hàng": Chỉ hiển thị `type = 'delivery'`
- **Search Panel**: Thêm 2 fields để lọc nhanh
  - `hlv_partner_type`: Loại liên hệ (Công ty / Cá nhân)
  - `hlv_filter_tag_ids`: Tags phân loại (Customer, Vendor, Main, Delivery)
- **Context**: Sửa `contacts.action_contacts` context `{'default_is_company': True}`

---

## 4. Luồng xử lý chính (Main Flows)

### 4.1. Lọc Contacts mặc định
```
User mở Contacts
  → Search view hiển thị filters: "Liên hệ chính", "Địa chỉ giao hàng"
  → Search Panel hiển thị: Loại liên hệ, Phân loại tags
  → User có thể bỏ filter để xem tất cả
```

### 4.2. Tự động phân loại (Tagging)
```
Partner được tạo/cập nhật
  → `_compute_hlv_filter_tag_ids()` được gọi
  → Kiểm tra customer_rank / sale.order
  → Kiểm tra supplier_rank / purchase.order
  → Kiểm tra parent_id / type
  → Gắn tags tương ứng
```

### 4.3. Đồng bộ MISA
```
User click "Cập nhật thông tin từ MISA"
  → Gọi MISA API (get_data với dataType: di_customer, di_vendor)
  → Parse dữ liệu (xử lý string/JSON trong Data field)
  → Build map: code → record, name → record
  → Search partners: parent_id=False, type!=delivery
  → Match: company_registry → account_object_code
  → Fallback: name → account_object_name
  → Update: vat, company_registry
  → Notify kết quả
```

---

## 5. Dependencies

- **Core**: `base`, `contacts`
- **Business**: `sale`, `purchase`
- **External**: `misa_fetch_po_button` (cho MISA API utilities)

---

## 6. Hướng dẫn mở rộng (Extension Guide)

### 6.1. Thêm tag mới
1. Thêm record trong `data/filter_tag_data.xml`
2. Thêm logic trong `_compute_hlv_filter_tag_ids()` (models/res_partner.py)

### 6.2. Thêm keyword cho "Convert to Company"
1. Sửa danh sách `keywords` trong `data/ir_actions_server.xml`

### 6.3. Thêm field sync từ MISA
1. Thêm logic trong `action_misa_update_bulk()` (models/hlv_contact_misa_sync.py)
2. Lưu ý: Xử lý robust parsing cho Data field (có thể là string hoặc dict)

---

## 7. Lưu ý quan trọng

- **Computed Fields**: `hlv_filter_tag_ids` là stored field (`store=True`), được tự động tính toán khi partner thay đổi.
- **MISA Robustness**: Dữ liệu MISA API trong field `Data` có thể là chuỗi JSON-encoded hoặc dict - luôn kiểm tra `isinstance(data, str)`.
- **Permissions**: Module yêu cầu quyền truy cập `res.partner` - đã khai báo trong `security/ir.model.access.csv`.
