# Tài liệu Kỹ thuật - Google Ads Automation

**Module:** `google_ads_automation`  
**Version:** 18.0.2.0.1

**Mục đích:** Tích hợp toàn diện Odoo với hệ sinh thái Google Ads, bao gồm:
1. **Theo dõi Chuyển Đổi & Cấu Hình GTM (Conversion Tracking & Tag Management):** Quản lý thẻ GTM, theo dõi đơn hàng WooCommerce và đồng bộ cấu hình GTM.
2. **Product Feed:** Liên kết Sản phẩm Odoo ↔ Chiến dịch (Campaign) Google Ads.
3. **Smart Rule Engine (Chiến lược tự động):** Tự sinh Rules điều khiển thầu/trạng thái dựa trên Tồn kho, Biên lợi nhuận, và ROAS.
4. **Mutate API:** Thực thi hành động Bật/Tắt chiến dịch tự động lên Google Ads.
5. **Chế Độ Demo Toàn Trị:** Giả lập toàn bộ luồng hoạt động mà không cần tài khoản Ads thật.

---

## 1. Cấu trúc thư mục

```text
google_ads_automation/
├── __init__.py
├── __manifest__.py
├── TECHNICAL.md
├── models/
│   ├── google_ads_account.py        # Core: OAuth, GTM API credentials, Demo Seeder
│   ├── google_ads_campaign.py       # Campaign data + metrics
│   ├── google_ads_ad_group.py       # Ad Group data + metrics
│   ├── google_ads_ad.py             # Ad data + metrics
│   ├── google_ads_tag.py            # ★ Quản lý Tag/GTM, sinh JS/PHP snippet, GTM API Fetcher
│   ├── google_ads_gtm_item.py       # ★ Lưu Tag/Trigger/Variable đồng bộ từ GTM (Read-Only)
│   ├── google_ads_conversion.py     # ★ Lượt chuyển đổi (Demo WooCommerce mua hàng), tính ROAS
│   ├── google_ads_product_feed.py   # Product Feed liên kết SP Odoo & Campaign
│   ├── google_ads_strategy.py       # Sinh Rules tự động theo bộ 5 chiến lược cốt lõi
│   ├── google_ads_rule.py           # Engine đánh giá độ thỏa mãn của Rule & thực thi
│   └── google_ads_rule_log.py       # Ghi log kết quả thực thi Rules
├── services/
│   └── google_ads_mutate.py         # Mutate API (Pause/Enable)
├── wizard/
│   └── google_ads_product_feed_wizard.py  # Wizard chọn nhanh Sản phẩm
├── security/
│   ├── ir.model.access.csv          # Quyền User vs Manager
│   └── google_ads_security.xml
└── views/
    ├── google_ads_tag_views.xml            # UI Cấu hình GTM, Snippet code
    ├── google_ads_conversion_views.xml     # UI Ghi nhận Lượt chuyển đổi
    ├── ... (các view khác)
    └── menu_views.xml                      # Cây Menu chính
```

---

## 2. Kiến trúc & Luồng xử lý (Chuỗi Domino)

Module được thiết kế theo cấu trúc Domino, Data từ Frontend (Web) chảy về Odoo và kích hoạt tự động hóa.

### 2.1. Tag Management & Data Collection (`google.ads.tag`)
- Tự động sinh Script Code (`<head>`, `<body>`, PHP cho WooCommerce) dựa trên `GTM Container ID` hoặc `AW-ID`.
- **GTM API Sync (Đồng bộ GTM):** Kết nối Google API v2 kéo danh sách Tags, Triggers, Variables về lưu tại `google.ads.gtm.item`. Toàn bộ quá trình là **GET Request (Read-Only)**, sử dụng Scope `tagmanager.readonly` đảm bảo an toàn tuyệt đối 100% không làm hỏng cấu hình GTM thực tế.

### 2.2. Conversion Tracking & Offline Upload (`google.ads.conversion`)
- Lưu trữ các sự kiện chuyển đổi (Purchase, Lead...) có gắn `gclid`.
- **Upload Offline (Bỏ qua GTM):** Cho phép đẩy trực tiếp dữ liệu chuyển đổi lên Google Ads API qua `GoogleAdsConversionService`. Giúp ghi nhận doanh thu chính xác ngay cả khi GTM bị chặn.
- **Tính toán ROAS thực:** Doanh Thu / Chi phí Quảng Cáo của Campaign.

### 2.3. Product Feed (`google.ads.product.feed`)
- Liên kết Database sản phẩm vật lý (`product.template`) vào Chiến dịch Google Ads.
- Cung cấp các thông số theo thời gian thực (Computed fields): `qty_available` (tồn kho), `margin_percent` (biên lợi nhuận), `avg_daily_sales` (tốc độ bán), `stock_status` (trạng thái kho).

### 2.4. Smart Strategy & Rules (`google.ads.strategy` & `google.ads.rule`)
- AI Brain của hệ thống. Thay vì người dùng phải tự if/else, họ chỉ cần chọn Strategy (Chiến lược).
- Ví dụ: Chiến lược **"Bảo Vệ Hàng Sắp Hết"** (Tồn thấp → Pause), **"Cân bằng tự động"** (ROAS cao + Tồn nhiều → Push ngấn sách).
- `action_generate_rules()` sẽ đọc data từ Product Feed và Conversion, tự động đẻ ra các bản ghi Rule.
- Khi Rule chạy, nó đánh giá lại điều kiện (Condition) một lần nữa và Trigger hành động (Action).

### 2.5. Executor / Mutate API (`services/google_ads_mutate.py`)
- Nhận lệnh từ Rule Engine (ví dụ: `action = 'pause_campaign'`).
- Bắn lệnh PUT qua Google Ads API để thực thi thật. Nằm trong cấu trúc an toàn: chỉ thực thi nếu `Strategy.is_live = True` (Luồng thật).

### 2.6. Campaign & Ad Group Creation Logic (Tạo mới)
Hệ thống cho phép tạo mới chiến dịch và nhóm quảng cáo trực tiếp từ Odoo lên Google Ads API.

#### Ma trận tương thích (Compatibility Matrix)
Khi tạo Nhóm quảng cáo, `AdGroupType` phải tương thích với `AdvertisingChannelType` của Chiến dịch cha:

| Campaign Type | Supported Ad Group Types | Ghi chú |
|---|---|---|
| **SEARCH** | `SEARCH_STANDARD`, `SEARCH_DYNAMIC_ADS` | DSA yêu cầu cấu hình Campaign DSA |
| **DISPLAY** | `DISPLAY_STANDARD` | |
| **SHOPPING** | `SHOPPING_PRODUCT_ADS` | Yêu cầu Merchant Center ID |
| **VIDEO** | `VIDEO_TRUE_VIEW_IN_STREAM`, `VIDEO_BUMPER`, `VIDEO_OUTSTREAM` | |
| **PERFORMANCE_MAX** | **N/A (Asset Group)** | PMax không dùng Ad Group |

#### Atomic Mutate for PMax
Để thỏa mãn **Brand Guidelines** của Google (bắt buộc có Logo & Business Name khi tạo PMax qua API), module sử dụng `GoogleAdsService.mutate` để thực hiện giao dịch nguyên tử:
1. Tạo `Asset` (Business Name).
2. Tạo `Asset` (Logo Image).
3. Tạo `Campaign` (Tạm giữ ID `-1`).
4. Liên kết Asset vào Campaign ID `-1`.

---

## 3. Chế Độ Demo (Safe Mode)

Tính năng cốt lõi cho việc testing/UAT. Khi `google.ads.account.is_demo = True`:
- Không cần khai báo API Credentials thật.
- **Tự sinh Data Giả:** Sinh Campaign, Ad Group, Ad với số ảo. Sinh Orders ảo cho Conversion Tracking (WooCommerce Demo). Sinh 16 mẫu Tag/Trigger GTM ảo.
- **Giả lập Mutate:** Rule thực thi action `pause` sẽ chỉ Update trạng thái ở DB Odoo và in Log thành công, bỏ qua bước gọi HTTP Request sang hệ thống máy chủ Google.
- *Ngoại lệ API:* Nếu đang trong Demo Mode nhưng User cố tình nhập đủ API Token ở phần GTM Tag, thì tính năng Sync GTM vẫn sẽ **Ưu tiên gọi API thật** để User có thể test tính năng kéo dữ liệu mà không ảnh hưởng luồng Mutate Ads.

---

## 4. Hướng dẫn mở rộng (Dành cho Developer)

- **Thêm loại Tag/Trigger mới vào GTM Sync:** Bổ sung mapping type trong dictionary của hàm `_fetch_gtm_endpoint` (`google_ads_tag.py`).
- **Thêm Strategy mới cho Ads:** 
  1. Thêm Enum vào `strategy_type` (`google_ads_strategy.py`).
  2. Định nghĩa hàm `_generate_rules_ten_chien_luoc()`.
- **Thêm Điều kiện (Condition) đánh giá mới:**
  1. Khai báo Enum trong `google_ads_rule.py`.
  2. Code logic xử lý so sánh (`<`, `>`, `=`) trong hàm `_evaluate_condition_value()`.
- **Phát triển Mutate API:**
  Bổ sung hàm định dạng Resource trong file `services/google_ads_mutate.py` (Ví dụ: `create_campaign`).
- **Nâng cấp Offline Conversion:**
  Chỉnh sửa `GoogleAdsConversionService` để hỗ trợ thêm các field metadata (`user_identifier`, hay `custom_variable`).
