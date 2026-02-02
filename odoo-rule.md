---
trigger: always_on
---

1. Nguyên tắc cốt lõi (Core Principles)
Odoo ORM > SQL: Luôn ưu tiên sử dụng các phương thức ORM (search, browse, create, write, unlink) thay vì viết raw SQL (cr.execute). Chỉ dùng SQL khi thực sự cần thiết cho hiệu suất (performance) và phải báo cáo lý do.
Kế thừa (Inheritance) > Sửa đổi: Không bao giờ sửa trực tiếp vào source code gốc (Odoo addons). Luôn tạo module mới và sử dụng cơ chế kế thừa (_inherit).
DRY (Don't Repeat Yourself): Tận dụng các mixin có sẵn (mail.thread, mail.activity.mixin) thay vì viết lại logic từ đầu.

2. Python & ORM (Backend Rules)
Imports: Import theo thứ tự: Thư viện chuẩn Python -> Thư viện bên thứ 3 -> Odoo imports (from odoo import ...).
Model Definition:
Luôn định nghĩa _description cho mọi Model (bắt buộc để tránh warning log).
Sử dụng fields.Command (e.g., [Command.link(id)], [Command.clear()]) cho các thao tác trên field One2many/Many2many thay vì dùng list magic tuple cũ (4, id, 0).
Decorators:
Sử dụng @api.depends cho Computed Fields. Phải liệt kê đầy đủ các field phụ thuộc.
Sử dụng @api.constrains để validate dữ liệu thay vì override hàm create/write nếu có thể.
Sử dụng @api.onchange cẩn thận (chỉ cho UI logic), không dùng nó để thay thế logic tính toán lưu xuống database.
Singleton: Khi viết method trong Model, luôn giả định self là một RecordSet. Nếu logic chỉ áp dụng cho 1 bản ghi, hãy dùng self.ensure_one() ở đầu hàm.
Translations: Bọc tất cả các string hiển thị cho user bằng _() từ odoo.tools.translate.

3. XML & Views (Frontend Rules)
XPath: Luôn sử dụng position="before", after, hoặc inside. Hạn chế tối đa dùng position="replace" trừ khi muốn xóa hẳn element đó, vì nó làm hỏng khả năng tương thích của các module khác.
No IDs Hardcode: Tuyệt đối không hardcode ID số nguyên (database ID) trong XML. Hãy dùng XML ID (External ID).
Attributes: Trong Odoo 17/18, hạn chế dùng attrs="{...}". Hãy dùng các thuộc tính trực tiếp như invisible="condition", readonly="condition", required="condition".
Ví dụ đúng: <field name="age" invisible="is_student == False"/>
Tree/List View: Không định nghĩa logic phức tạp trong Tree View. Giữ cho nó đơn giản để tối ưu hiệu suất render.

4. Javascript & OWL (Web Client Rules)
Framework: Odoo 18 sử dụng OWL 2.0+. Không sử dụng jQuery hoặc Widget API cũ trừ khi đang maintain code legacy cực cũ.
Hooks: Sử dụng useState, useRef, useService... thay vì thao tác DOM trực tiếp.
Patching: Khi muốn sửa đổi hành vi của component có sẵn, hãy sử dụng hàm patch từ @web/core/utils/patch.
Assets: Đăng ký file JS/CSS trong __manifest__.py dưới mục 'assets':
web.assets_backend: Cho giao diện nội bộ.
web.assets_frontend: Cho giao diện Website/Portal.

5. Bảo mật & Quyền truy cập (Security Rules)
CSV File: Mọi Model mới tạo BẮT BUỘC phải có dòng tương ứng trong file security/ir.model.access.csv. Không để trống quyền truy cập.
Record Rules: Luôn xem xét logic multi-company. Dữ liệu công ty A không được phép thấy bởi user công ty B (sử dụng field company_id và rule ['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]).
Sudo: Hạn chế tối đa việc dùng sudo(). Nếu dùng, phải có comment giải thích lý do (ví dụ: User Portal cần tạo record nhưng không có quyền đọc config).
Sanitize: Khi render HTML field (fields.Html), đảm bảo sanitize=True (mặc định) trước khi render.

6. Structure & Manifest
Manifest:
Luôn khai báo đúng depends. Nếu code dùng field của module sale, phải depend sale.
Version module theo chuẩn: 18.0.x.y.z.
Naming Convention:
File Python: snake_case.py
Class Python: PascalCase
XML ID: module_name.model_name_action_name

7. Odoo 18 Specific Context
Chú ý sự thay đổi trong cách gọi Controllers.
Kiểm tra các method đã bị Deprecated trong v16/v17 vì v18 có thể đã xóa bỏ hoàn toàn.
Sử dụng frozen=True cho các constant global để tối ưu bộ nhớ.

8. MISA API Integration Rules
Khi gọi API MISA (đặc biệt là endpoint `get_data` hoặc `paging_filter`):
- Tham số Payload: Phải sử dụng đúng `dataType` (ví dụ `di_customer`, `di_vendor`) và các phím phân trang phải dùng camelCase (`pageIndex`, `pageSize`). Các tham số `filter` và `sort` thường phải truyền dưới dạng chuỗi JSON (`json.dumps()`).
- Robust Parsing: Dữ liệu trả về trong trường `Data` có thể là một chuỗi JSON-encoded thay vì list/dict. Luôn kiểm tra `isinstance(data, str)` và thực hiện `json.loads()` trước khi truy cập các thuộc tính để tránh lỗi `AttributeError`.
- Sudo: Luôn sử dụng `.sudo()` khi thực hiện các thao tác ghi dữ liệu (write) hàng loạt từ API để đảm bảo không bị chặn bởi phân quyền người dùng thực thi.

9. Tự động cập nhật quy tắc (Self-Evolution)
Mỗi khi gặp một vấn đề mới liên quan đến sự khác biệt phiên bản (Odoo 17 vs 18), sự thay đổi hàm/biến, hoặc lỗi logic dữ liệu nghiêm trọng (ví dụ: AttributeError do kiểu dữ liệu API không đồng nhất), AI phải tiến hành cập nhật kiến thức này vào file quy tắc dự án (`.agent/rules/...`) để tránh lặp lại lỗi đó trong tương lai.

9.1. Tính số lượng đã giao (Delivered Quantity Calculation)
**QUAN TRỌNG**: Khi cần tính tổng số lượng đã giao của một Sale Order, **LUÔN SỬ DỤNG** trường `qty_delivered` từ `sale.order.line`, **KHÔNG BAO GIỜ** tính trực tiếp từ `stock.move` hoặc `stock.move.line`.

**Lý do**:
- Trong các cấu hình delivery nhiều bước (2-step hoặc 3-step: Pick → Pack → Out), mỗi sản phẩm sẽ đi qua nhiều stock.picking và tạo ra nhiều stock.move/stock.move.line tương ứng.
- Nếu tính tổng `qty_done` từ tất cả các `stock.move.line` trong các picking đã `done`, bạn sẽ **đếm trùng** cùng một số lượng nhiều lần (ví dụ: đếm 3 lần với 3-step delivery).
- Odoo đã cung cấp sẵn computed field `qty_delivered` trên `sale.order.line` với điều kiện:
  - `parent.state != 'cancel'`
  - `qty_delivered_method == 'manual'` hoặc `is_downpayment`
  
**Cách làm đúng**:
```python
delivered_by_product = {}
for line in sale_order.order_line:
    prod = line.product_id
    if not prod or prod.type == 'service':
        continue
    qty_delivered = float(line.qty_delivered or 0.0)
    # Group theo product nếu cùng sản phẩm xuất hiện nhiều dòng
    delivered_by_product[prod] = delivered_by_product.get(prod, 0.0) + qty_delivered
```

**Lưu ý đặc biệt**:
- Cùng một sản phẩm có thể xuất hiện ở **nhiều dòng** trong Sale Order → Phải **cộng dồn** `qty_delivered` khi group theo `product_id`.
- Field `qty_delivered` đã được Odoo tính toán tự động dựa trên các stock.move cuối cùng (outgoing moves), phú hợp cho mọi loại delivery flow.

9.2. MISA Sale Order Sync (`misa_fetch_po_button` module)
**Module**: `custom_addons/misa_fetch_po_button` - Đồng bộ Sale Order và Picking từ MISA ERP

**Nguyên tắc quan trọng**:

**A. Sale Order Line Sync - KHÔNG GROUP theo Product Code**
- ❌ **SAI**: Map SOL theo `default_code` → gộp nhiều dòng MISA cùng product thành 1 SOL
- ✅ **ĐÚNG**: Mỗi dòng MISA = 1 SOL riêng biệt, kể cả khi cùng product

**Lý do**: MISA có thể có nhiều dòng cùng sản phẩm với qty/giá/ghi chú khác nhau. Ví dụ:
```
MISA: C:100 (dòng 1) + C:100 (dòng 2) 
→ Odoo phải có 2 SOL riêng, KHÔNG gộp thành 1 SOL với qty=200
```

**Logic sync đúng** (trong `_sync_so_lines_from_misa_no_picking`):
```python
# 1. Thu thập tất cả dòng MISA (KHÔNG group)
misa_sol_data = []  # Mỗi dòng MISA = 1 item

# 2. Match với SOL hiện có
# Pass 1: Product + Qty khớp (chính xác)
# Pass 2: Chỉ Product khớp (khi qty thay đổi)

# 3. Update SOL đã match
# 4. Tạo mới SOL cho dòng MISA chưa match
# 5. Xóa/cắt SOL không còn trong MISA
```

**B. Stock Move Linking - Luôn link với Sale Order Line**
Khi tạo `stock.move` mới, **BẮT BUỘC** phải link với `sale.order.line` qua field `sale_line_id`:

```python
# Tìm SOL có product này và còn qty chưa giao
sol = self.order_line.filtered(
    lambda l: l.product_id == prod 
    and (l.product_uom_qty - l.qty_delivered) > 0.001
)[:1]

move_vals = {
    'product_id': prod.id,
    'product_uom_qty': needed_qty,
    'sale_line_id': sol.id if sol else False,  # ← QUAN TRỌNG
    # ... other fields
}
```

**Tại sao quan trọng**:
- Odoo dùng `sale_line_id` để tính `qty_delivered` cho SOL
- Nếu không link → SOL.qty_delivered sẽ không cập nhật
- Picking sẽ không hiển thị đúng trong Sale Order

**C. Sync Fields từ MISA**
Các field cần sync từ MISA sang Sale Order Line:
- `ProductIDText` → `product_id` (qua `_get_or_create_product`)
- `Description` → `name`
- `Amount` → `product_uom_qty` (đã convert UoM)
- `Price` → `price_unit` (đã convert UoM)
- `DiscountPercent` → `discount`
- `Note` / `DescriptionProduct` → `note`
- `CustomField4` → `x_studio_product_status` ← **KHÔNG ĐƯỢC BỎ QUÁ**
- `TaxPercentIDText` → `tax_id`

**D. Partial Resync Logic**
Khi đồng bộ SO đã có picking done (hàm `_partial_resync_open_pickings_when_done_present`):

1. **Tính delivered**: Dùng `sale.order.line.qty_delivered` (KHÔNG dùng picking.move_line_ids)
2. **Tính MISA total**: Sum qty từ MISA lines (đã convert UoM)
3. **Tính needed**: `needed = misa_total - delivered` (cho mỗi product)
4. **Check over-delivery**: Nếu `delivered > misa_total` → CHẶN đồng bộ (raise UserError)
5. **Update picking mở**: Cập nhật/tạo move theo `needed_in_open_by_product`

**E. Common Pitfalls**
1. ❌ Group SOL theo product code → Mất dữ liệu khi MISA có nhiều dòng cùng product
2. ❌ Tính delivered từ move_line.qty_done → Đếm trùng trong multi-step delivery
3. ❌ Không link move với SOL → qty_delivered không cập nhật
4. ❌ Quên sync `x_studio_product_status` → Mất thông tin trạng thái sản xuất
5. ❌ Không handle case "thêm dòng mới cùng product" → SOL không được tạo
   - **Incorrect**: `<setting id="my_setting">` → This ID format is rejected in Odoo 18
   - **Correct**: Use `<record id="res_config_settings_my_setting" model="res.config.settings">` with standard record definition

### 11.5. Cron Jobs with `model_id` - Odoo 18 Issue

**Problem**: In Odoo 18, defining `ir.cron` records in XML with `model_id` using `ref` or `search` attributes often causes `ParseError` during module installation.

**Why**: The XML parser has issues resolving the `model_id` reference at load time.

**Solution**: 
1. **Set `active="False"` by default** in the XML cron definition
2. **Enable via Settings UI**: After module installation, users should go to Settings > Technical > Automation > Scheduled Actions and manually activate the cron job. The UI correctly handles the `model_id` field.
3. Alternatively, enable "Auto Crawl" in Inventory Settings, which will activate the cron programmatically.

**Example**:
```xml
<record id="ir_cron_auto_crawl" model="ir.cron">
    <field name="name">Auto Crawl Queue</field>
    <field name="model_id" search="[('model', '=', 'product.template')]"/>
    <field name="state">code</field>
    <field name="code">model.cron_crawl_batch()</field>
    <field name="active" eval="False"/>  <!-- Disabled by default -->
</record>
```

**Deprecated Fields in Odoo 18**:
- ❌ `numbercall` - No longer exists, will cause `ValueError: Invalid field 'numbercall'`
- ❌ `doall` - No longer exists, will cause `ValueError: Invalid field 'doall'`
- ✅ Use only: `name`, `model_id`, `state`, `code`, `user_id`, `interval_number`, `interval_type`, `active`


10. Settings View for Odoo 18
Cấu trúc `res.config.settings` view inheritance đã thay đổi trong Odoo 18.
- KHÔNG sử dụng: `<xpath expr="//div[hasclass('settings')]" position="inside">` (đã bị loại bỏ trong base view).
- SỬ DỤNG: `<xpath expr="//form" position="inside">` kết hợp với cấu trúc `<app>`, `<block>`, `<setting>`.
  Ví dụ:
  ```xml
  <app data-string="My App" string="My App" name="my_app_name">
      <block title="Block Title" name="block_name">
          <setting string="Setting Label" help="...">
              <field name="my_field"/>
          </setting>
      </block>
  </app>
  ```

11. Odoo 18 Troubleshooting & Fixes
11.1. Views: Replaced `tree` with `list`
- **Lỗi**: `Invalid view type: 'tree'`
- **Nguyên nhân**: Trong Odoo 18 (và các phiên bản mới của OWL web client), tag `<tree>` đã bị loại bỏ hoặc không còn được hỗ trợ trong một số context nhất định (ví dụ: view nhúng).
- **Giải pháp**: Sử dụng tag `<list>` thay thế cho `<tree>`.
  ```xml
  <!-- CŨ (Odoo 17 trở về trước) -->
  <tree> ... </tree>
  
  <!-- MỚI (Odoo 18) -->
  <list> ... </list>
  ```

11.2. Cron Job & External IDs (ParseError)
- **Lỗi**: `ParseError: while parsing ...` tại dòng khai báo `ir.cron` với `ref="module.model_name"`.
- **Hiện tượng**: Server báo lỗi khi cố gắng resolve External ID của model trong file XML data, mặc dù syntax đúng (`ref="product.model_product_template"`).
- **Giải pháp tạm thời**:
  1. Thử dùng `eval="ref('module.model_name')"` thay vì `ref=`.
  2. Nếu vẫn lỗi, comment lại `ir_cron_data.xml` trong manifest và tạo Cron Job thủ công qua UI.
  3. Đảm bảo file định nghĩa server action (nếu có dùng chung `ref`) được load trước file cron trong `__manifest__.py`.

11.3. Security cho Transient Models
- **Nguyên tắc**: Wizard (TransientModel) cũng CẦN phải có quyền truy cập trong `ir.model.access.csv`, giống như Model thường. Đừng quên thêm dòng cấp quyền (thường là cho `base.group_user`).

11.4. Settings View Odoo 18 Structure
- **Lỗi**: `Cannot locate element '<xpath expr="//div[hasclass('settings')]">'`
- **Nguyên nhân**: Cấu trúc view `res.config.settings` đã thay đổi hoàn toàn.
- **Giải pháp**: Xpath vào `//form` và sử dụng tag `<app>`, `<block>`, `<setting>`.
  ```xml
  <xpath expr="//form" position="inside">
      <app string="My Module" name="my_module">
          <block title="Section Name">
              <setting string="Label" help="...">
                  <field name="my_field"/>
              </setting>
          </block>
      </app>
  </xpath>
  ```