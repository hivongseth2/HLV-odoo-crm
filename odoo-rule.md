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