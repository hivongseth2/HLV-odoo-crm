# Kế Hoạch Đồng Bộ Giá từ Odoo lên WordPress

## 1. TỔNG QUAN HỆ THỐNG HIỆN TẠI

### Quy trình hiện tại:
```
MISA → Odoo (qua misa_fetch_po_button) → ??? → WordPress
```

- **MISA**: Đã đồng bộ PO/Product/Prices từ MISA vào Odoo thành công
- **Odoo**: Lưu giá ở 3 trường: `list_price` (giá bán lẻ), `standard_price` (giá vốn), `x_studio_gi_bn_thng_mi` (giá thương mại)
- **WordPress**: Hiện chỉ nhận webhook đơn hàng từ WP (không phải đồng bộ hai chiều)

### Kiến trúc module:
```
misa_fetch_po_button/
  ├── models/
  │   ├── misa_po_fetch.py (fetch từ MISA)
  │   ├── misa_po_sync.py (wizard đồng bộ PO theo mã)
  │   ├── sale_api_import_wizard.py (import từ API)
  │   ├── sale_order_misa_sync.py (đồng bộ SO)
  │   └── ...
  └── views/
      └── misa_po_sync_view.xml (UI)
```

---

## 2. THIẾT KẾ GIẢI PHÁP

### 2.1 Cấu Trúc Module Mới
```
wordpress_sync/
  ├── __init__.py
  ├── __manifest__.py
  ├── models/
  │   ├── __init__.py
  │   ├── wordpress_config.py (cấu hình WordPress API)
  │   ├── wordpress_price_sync.py (wizard đồng bộ giá)
  │   └── product_sync_log.py (log đồng bộ)
  ├── views/
  │   ├── wordpress_config_view.xml (settings)
  │   ├── wordpress_price_sync_view.xml (wizard)
  │   └── product_sync_log_view.xml (log)
  ├── controllers/
  │   └── main.py (webhook handlers - optional)
  ├── static/
  │   └── description/
  │       └── icon.png
  └── security/
      └── ir.model.access.csv
```

### 2.2 Mô hình Dữ liệu

#### Model 1: `wordpress.config`
```python
- name: Char (tên config, ví dụ: "Main Store")
- wc_domain: Char (https://hoanglongvu.com - KHÔNG có dấu / ở cuối)
- wc_key: Char (consumer key - encrypted)
- wc_secret: Char (consumer secret - encrypted)
- sync_price_type: Selection ([
    'list_price',           # Giá bán lẻ
    'x_studio_gi_bn_thng_mi' # Giá thương mại
  ])
- sync_sale_price: Boolean (có đồng bộ sale price không)
- sync_stock_status: Boolean (có đồng bộ trạng thái kho không)
- last_sync_date: Datetime
- active: Boolean
```

#### Model 2: `product.sync.log`
```python
- product_id: Many2one (product.template)
- sku: Char (mã sản phẩm)
- sync_type: Selection (['manual', 'auto', 'cron'])
- status: Selection (['success', 'failed', 'skipped'])
- message: Text (chi tiết kết quả)
- wc_product_id: Integer (ID trên WordPress)
- sync_date: Datetime
- regular_price: Float (giá đã đồng bộ)
- sale_price: Float (sale price đã đồng bộ)
```

### 2.3 Hàm Synchronization

#### Cấu hình API (tương tự code mẫu):
```python
def wc_get(path):
    """GET request tới WooCommerce API"""

def wc_put(path, payload):
    """PUT request tới WooCommerce API"""

def wc_cache_purge(sku):
    """Xoá cache LiteSpeed"""
```

#### Logic đồng bộ (tương tự code mẫu):
```
1. Lấy danh sách product/variations từ Odoo
2. Với mỗi product:
   a. Lấy giá từ Odoo (list_price, x_studio_gi_bn_thng_mi, stock)
   b. Tìm product trên WordPress bằng SKU (regular.product_code)
   c. Nếu tìm thấy:
      - PUT product với data: regular_price, sale_price, stock_status
      - Log thành công
   d. Nếu không tìm thấy:
      - Log SKIP: "Không tìm thấy SKU: XXX"
3. Xoá cache LiteSpeed
```

#### Variant handling:
```
- product.type == 'variation' → PUT /products/{parent_id}/variations/{id}
- product.type khác → PUT /products/{id}
```

### 2.4 Mô hình Stock Status Mapping
```python
STOCK_MAPPING = {
    'Còn hàng': 'instock',
    'Hết hàng': 'outofstock',
    'Ngừng kinh doanh': 'outofstock'
}
```

### 2.5 Mô hình Sale Price Logic
```
1. Nếu x_studio_gi_bn_thng_mi > 0 và < list_price:
   regular_price = list_price
   sale_price = x_studio_gi_bn_thng_mi

2. Nếu không (x_studio_gi_bn_thng_mi = 0 hoặc = list_price):
   regular_price = list_price
   sale_price = '' (xoá sale price trên WP)
```

---

## 3. NHỮNG YEU CẦU CẦN CLARIFY

Trước khi implement, cần xác nhận:

1. **Giá nào để đồng bộ?**
   - Giá bán lẻ (list_price)?
   - Giá thương mại (x_studio_gi_bn_thng_mi)?
   - Cả hai?

2. **Khuyến mãi (Sale Price)?**
   - Luôn dùng `x_studio_gi_bn_thng_mi` làm sale_price?
   - Có logic thêm ngoài (ví dụ: kiểm tra campaign, date)?

3. **Tần suất đồng bộ?**
   - Manual: User click button (tương tự PO sync)
   - Auto: Khi product được edit trong Odoo
   - Cron: Job chạy định kỳ (hằng ngày, hằng giờ?)
   - Combinations?

4. **Stock Status?**
   - Đồng bộ trạng thái kho không?
   - Nếu có: lấy từ field nào trong product?

5. **WordPress Configuration?**
   - Lưu trong System Parameters hay Config Model?
   - Có multiple WordPress stores không? (1 hay nhiều?)

6. **Logging/Reporting?**
   - Cần chi tiết log mỗi product không?
   - Cần dashboard/report cho sync history?

---

## 4. IMPLEMENTATION STEPS

### Phase 1: Core Infrastructure (Tầng nền)
1. Tạo module `wordpress_sync`
2. Tạo model `wordpress.config` + view settings
3. Tạo WooCommerce API utils (wc_get, wc_put, etc.)
4. Thêm dependencies trong `__manifest__.py`

### Phase 2: Synchronization Logic
1. Tạo model `product.sync.log`
2. Tạo transient model `wordpress.price.sync` (wizard)
3. Implement hàm sync logic chính:
   - `_sync_single_product()`
   - `_sync_multiple_products()`
4. Implement wizard form + button action

### Phase 3: UI & Integration
1. Tạo views cho wizard form
2. Thêm menu item vào Product module
3. (Tuỳ chọn) Thêm cron job + auto-sync khi product edit
4. Thêm public API endpoint (tương tự `api_sync_po_by_code`)

### Phase 4: Testing & Refinement
1. Test với WordPress staging
2. Handle edge cases (missing SKU, network errors, etc.)
3. Performance optimization (batch requests)

---

## 5. CODE PATTERN (Dựa vào mẫu hiện tại)

Sẽ sử dụng pattern tương tự `misa_po_sync.py`:

```python
# Transient Model (Wizard)
class WordpressPriceSync(models.TransientModel):
    _name = "wordpress.price.sync"

    sync_type: Selection ([
        'single',      # 1 product
        'category',    # category
        'all'          # all products
    ])
    product_id: Many2one (product.template)
    category_id: Many2one (product.category)

    def action_sync(self):
        """Main action được gọi từ button"""
        result = self._sync_core(...)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            ...
        }

    def _sync_core(self):
        """Core logic đồng bộ"""
        ...
        return {'ok': True, 'synced': count, ...}

# Inherit Product Template
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Thêm button "Sync to WP"
    def action_sync_to_wordpress(self):
        """Button action sync single product"""
        ...
```

---

## 6. DEPENDENCIES & CONFIGURATION

### Dependencies trong `__manifest__.py`:
```python
'depends': ['base', 'product', 'stock', 'website'],
```

### System Parameters (Nếu dùng):
```
- wordpress.domain: "https://hoanglongvu.com"
- wordpress.consumer_key: "ck_xxx"
- wordpress.consumer_secret: "cs_xxx"
```

### Hoặc Model-based Config:
```
wordpress.config record với tất cả config fields
```

---

## 7. ERROR HANDLING & LOGGING

Pattern tương tự MISA sync:

```python
def _wc_api_call_with_retry(path, method, payload=None, retries=3):
    """Retry 3 lần với delay exponential"""
    for i in range(retries):
        try:
            res = wc_call(path, method, payload)
            return res
        except ConnectionError:
            time.sleep(1000 * (i + 1))
    raise Exception("API call failed after retries")

def _log_sync(product_id, status, message, wc_id=None):
    """Log mỗi lần sync"""
    self.env['product.sync.log'].create({
        'product_id': product_id,
        'status': status,
        'message': message,
        'wc_product_id': wc_id,
    })
```

---

## 8. TÓNG TẮT

### Ưu điểm của thiết kế này:
- ✅ Tương tự pattern hiện tại (dễ maintain)
- ✅ Flexible (manual/auto/cron)
- ✅ Có logging đầy đủ
- ✅ Error handling robust
- ✅ Reusable API utils
- ✅ Dễ mở rộng cho multiple stores

### Phạm vi (Scope):
- ✅ Sync giá (regular + sale)
- ✅ Sync stock status
- ✅ Handle variants
- ✅ Cache purge (LiteSpeed)
- ❌ Sync descriptions, images, etc. (Phase 2)
- ❌ Bi-directional sync (Phase 2)

---

## 9. ESTIMATED EFFORT

- **Phase 1**: 2-3 hours (infrastructure)
- **Phase 2**: 3-4 hours (logic + testing)
- **Phase 3**: 1-2 hours (UI + integration)
- **Phase 4**: 1-2 hours (testing + refinement)

**Total**: ~8-10 hours = 1-1.5 days
