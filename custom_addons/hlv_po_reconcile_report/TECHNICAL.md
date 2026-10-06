# hlv_po_reconcile_report — Technical

## Mục đích
Cron hằng ngày (mặc định 19h GMT+7) đối chiếu Đơn mua hàng Odoo - MISA trong N ngày gần nhất, tạo file Excel, lưu lên Google Drive và gửi mail cho danh sách người nhận. Thay cho việc bấm tay nút "Đối chiếu Đơn mua hàng" trên Chrome extension.

## Cấu trúc
```
hlv_po_reconcile_report/
├── data/
│   ├── ir_config_parameter.xml  ← Gọi _init_default_params: tạo System Parameters nếu chưa có
│   └── ir_cron.xml              ← Cron ir_cron_po_reconcile_daily (active=False, noupdate)
├── models/
│   ├── po_reconcile_engine.py   ← reconcile_po(env, date_from, date_to): logic đối chiếu Odoo - MISA
│   ├── po_reconcile_report.py   ← AbstractModel hlv.po.reconcile.report: cron, upload Drive, gửi mail
│   └── po_reconcile_xlsx.py     ← build_reconcile_xlsx(): port của excel_export.js (extension), không import odoo
├── __manifest__.py
└── TECHNICAL.md
```

## Quy tắc kiến trúc
- **Logic đối chiếu độc lập**: `po_reconcile_engine.py`, ban đầu chép từ endpoint `/api/extension/po/reconcile_only` của `misa_purchase_request_sync` nhưng KHÔNG còn dùng chung. Sửa cách đối chiếu cho báo cáo → chỉ sửa ở đây; extension giữ logic riêng của nó. Gọi trực tiếp trong cron (không qua HTTP) nên không bị timeout khi nhiều đơn.
- Không phụ thuộc `misa_purchase_request_sync`; chỉ cần `misa_fetch_po_button` (`misa.api.utils`, `misa.config`) để gọi API MISA.
- Excel: chỉ ở `po_reconcile_xlsx.py`. Giữ cùng layout với `excel_export.js` của extension (sheet "Tổng hợp" + "Chi tiết").
- Google Drive: dùng tài khoản đã kết nối ở `custom_barcode_scan_redirect` qua System Parameters `gdrive.*`, nhưng KHÔNG import code module đó (`_gdrive_connect` tự dựng kết nối). Đổi cách xác thực Drive bên đó → kiểm tra lại `_gdrive_connect`.

## Luồng xử lý (`cron_send_daily_reconcile`)
1. Đọc người nhận `misa_po_reconcile_emails` (phân cách `,` hoặc `;`, chỉ lấy giá trị có `@`). Không có email hợp lệ → log warning, dừng.
2. Đọc `misa_po_reconcile_days` (mặc định 1): khoảng ngày = hôm nay (giờ VN) và N-1 ngày trước.
3. Gọi `reconcile_po` → `build_reconcile_xlsx` → tạo `ir.attachment`.
4. `_upload_to_drive`: đẩy file vào thư mục `DOI_CHIEU_DON_MUA_HANG` ở gốc My Drive (tự tạo). Lỗi → log, trả None, vẫn gửi mail.
5. Tạo `mail.mail` (kèm file, link Drive nếu có, `auto_delete=False`) và `send()` ngay, không chờ cron hàng đợi mail.

## Cấu hình
| System Parameter | Ý nghĩa |
|---|---|
| `misa_po_reconcile_emails` | Email nhận báo cáo, phân cách dấu phẩy. Tạo sẵn với giá trị tạm `chua_cau_hinh` (cron bỏ qua) |
| `misa_po_reconcile_days` | Số ngày lấy dữ liệu, tạo sẵn = `1` |

Hai param được `_init_default_params` tạo khi cài/upgrade nếu chưa có; giá trị đã cấu hình không bị ghi đè.

Giờ chạy: sửa **Next Execution Date** của cron trong Settings > Technical > Scheduled Actions (cron mặc định tắt, phải bật tay).

## Kiểm tra
`python models/po_reconcile_xlsx.py` — self-check dựng Excel (cần xlsxwriter).
