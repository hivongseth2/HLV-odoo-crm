# Tài liệu Kỹ thuật - Google Ads Automation

**Module:** `google_ads_automation`

**Mục đích:** Tích hợp Odoo với Google Ads API để quản lý tài khoản, đồng bộ chiến dịch, và tự động hóa quy trình tối ưu giá thầu / trạng thái chạy theo điều kiện logic (Rules).

## 1. Cấu trúc thư mục (Tree View)

```text
google_ads_automation/
├── __init__.py
├── __manifest__.py
├── data/
│   └── ir_cron_data.xml           # Định nghĩa Cron jobs thực thi Rule tự động
├── models/
│   ├── google_ads_account.py      # Quản lý cấu hình API & OAuth credentials
│   ├── google_ads_campaign.py     # Dữ liệu Chiến dịch (Campaign)
│   ├── google_ads_ad_group.py     # Dữ liệu Nhóm QC (Ad Group)
│   ├── google_ads_ad.py           # Dữ liệu Quảng Cáo (Ad)
│   ├── google_ads_rule.py         # Cấu hình Quy tắc tự động (Automation Rules)
│   └── google_ads_rule_log.py     # Lịch sử thực thi quy tắc
├── security/
│   ├── ir.model.access.csv        # Phân quyền truy cập các model
│   └── google_ads_security.xml    # Định nghĩa Security Groups (nếu có)
└── views/
    ├── menu_views.xml             # Main menu và Submenus
    └── ..._views.xml              # Giao diện Tree/Form cho các models
```

## 2. Quy tắc Kiến trúc & Luồng xử lý chính

### 2.1. Authentication & Client Initialization
- Mọi tương tác với Google Ads được tập trung qua hàm `_get_google_ads_client()` nằm tại `google.ads.account`.
- Hàm này sử dụng thư viện `google-ads` Python client. Đọc credentials lưu trên model và khởi tạo connection client.

### 2.2. Luồng Đồng bộ (Sync Flow)
- Đồng bộ dữ liệu đi theo luồng phân cấp: `Campaigns -> Ad Groups -> Ads`.
- Mỗi hàm `action_sync_*` sẽ tạo một truy vấn `GAQL (Google Ads Query Language)` để lấy fields trực tiếp (kèm theo metrics) từ bảng phân tích của Google.
- Model sử dụng Field `google_campaign_id`, `google_ad_group_id`, `google_ad_id` như là External ID để đối chiếu `search([...])` tạo mới hoặc update.

### 2.3. Luồng Tự động hóa (Automation Flow)
1. Cron job `ir_cron_google_ads_evaluate_rules` được kích hoạt mỗi ngày (hiện được cấu hình an toàn bằng cách set `active="eval('False')"` theo format Odoo 18 trong XML).
2. Khi chạy, hệ thống sẽ thực thi hàm `cron_evaluate_all_rules()` trong `google.ads.rule`:
   - Lệnh sync tài khoản mới nhất (`action_sync_all_data`).
   - Lặp qua từng Rule active.
   - Tìm đối tượng có metrics thỏa mãn điều kiện Operator (>, <, =).
   - Ghi log vào `google.ads.rule.log`.
   - Cần implement: Gọi Mutate Service bắn tín hiệu đổi trạng thái sang nền tảng Google.

## 3. Hướng dẫn Mở rộng

- **Thêm tính năng Mutate API:** Hãy tạo thư mục `services/` (ví dụ `services/google_ads_mutate.py`), viết một utility class nhận `GoogleAdsClient` và đối tượng tương ứng định danh bởi ID để gọi các operation như `CampaignOperation` với action update status thành PAUSED. Sau đó import service này vào `google.ads.rule` để sử dụng.
- **Bổ sung chỉ số phân tích mới (Metrics):** Cần sửa đổi chuỗi câu truy vấn `SELECT` bên trong các hàm `action_sync_*` ở `google_ads_account.py`, sau đó khai báo thêm các field tương ứng trong các model Campaign, Ad Group, Ad. Đừng quên update logic write data map đúng tên trường trong quá trình batch stream.
- **Xử lý đồng bộ dữ liệu khối lượng siêu lớn:** Cân nhắc implement module queue_job. Tách `action_sync_all_data` thay vì chạy vòng for ngay tại cron thì bắn các queue job ứng dụng mô hình Worker phân tán để tránh Odoo Server Timeout.
