# TECHNICAL.md - hlv_smart_report_config

## Mục đích
Module này bổ sung khả năng cấu hình quy tắc in biên bản thông minh cho `stock.picking`. Thay vì phải chọn thủ công từng loại biên bản, hệ thống sẽ tự động tìm quy tắc phù hợp với khách hàng (hoặc regex tên khách hàng) và đề xuất/thực hiện in.

## Cấu trúc thư mục
```
hlv_smart_report_config/
├── models/
│   ├── hlv_report_rule.py    # Định nghĩa quy tắc (Rule) và các dòng báo cáo (Line)
│   └── stock_picking.py      # Kế thừa picking để thêm nút in và logic tìm rule
├── wizard/
│   ├── hlv_smart_print_wizard.py       # Wizard chọn báo cáo thủ công / xác nhận in
│   └── hlv_smart_print_wizard_views.xml # Form wizard popup
├── views/
│   ├── hlv_report_rule_views.xml        # Giao diện cấu hình quy tắc
│   └── stock_picking_views.xml          # Button trên form picking và action trên list
├── security/
│   └── ir.model.access.csv   # Phân quyền truy cập
├── __init__.py
└── __manifest__.py
```

## Logic xử lý chính

### 1. Tìm quy tắc (`_find_rule_for_picking`)
- Truy vấn tất cả `hlv.report.rule` đang hoạt động (`active=True`), sắp xếp theo `sequence`.
- Ưu tiên:
  - `match_type='partner'`: Kiểm tra `partner_id` của picking có nằm trong danh sách `partner_ids` của rule không.
  - `match_type='regex'`: Kiểm tra tên khách hàng có khớp với `partner_regex`.
  - `match_type='all'`: Quy tắc mặc định (thường đặt sequence cao nhất).

### 2. Luồng in biên bản (`action_smart_print`)
1. Tìm rule phù hợp.
2. Nếu tìm thấy rule VÀ có cấu hình báo cáo:
   - Mở wizard `hlv.smart.print.wizard`, tự động điền danh sách báo cáo từ rule.
3. Khi người dùng nhấn **In biên bản** trên wizard:
   - Hệ thống gọi một custom Action URL: `/hlv_smart/print_merged/<wizard_id>`.
   - Controller tại server sẽ:
     - Duyệt qua từng dòng biên bản trong wizard.
     - Render nội dung PDF cho từng loại.
     - Nhân bản nội dung dựa trên trường **Số bản in** (Copies).
     - Gộp tất cả (Merge) thành 1 file PDF duy nhất bằng `odoo.tools.pdf.merge_pdf`.
     - Trả về file PDF gộp cho trình duyệt tải về.
   - Ưu điểm: Giải quyết được giới hạn của trình duyệt (chặn tải nhiều file) và giới hạn của Odoo (deduplicate recordset IDs).

## Quy tắc thiết kế (DRY)
- Logic tìm kiếm rule được đặt tập trung tại model `hlv.report.rule`.
- Sử dụng controller để xử lý gộp PDF nhằm giữ cho mã nguồn sạch sẽ và chuyên nghiệp.

## Hướng dẫn mở rộng
- Để thêm tiêu chí lọc mới (ví dụ lọc theo Kho):
  - Thêm field vào `hlv.report.rule`.
  - Cập nhật logic trong `_find_rule_for_picking`.
  - Cập nhật form view rule.
