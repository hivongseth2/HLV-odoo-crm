# Tổng hợp Endpoint - Google Ads Automation

Tài liệu này liệt kê tất cả các điểm kết nối kỹ thuật (Endpoints) mà module sử dụng để giao tiếp nội bộ và bên ngoài.

---

## 1. Endpoints Nội bộ (Inbound - Controllers)
Đây là các URL được định nghĩa trong Odoo để tiếp nhận yêu cầu từ bên ngoài gọi vào.

| URL Path | Phương thức | Xác thực | Chức năng (Purpose) |
|---|---|---|---|
| `/google_ads/auth_callback` | `GET` | `user` | **OAuth 2.0 Callback:** Tiếp nhận Authorization Code từ Google, trao đổi lấy Refresh Token và lưu vào Odoo. |

---

## 2. Endpoints Bên ngoài (Outbound - API Services)
Đây là các dịch vụ mà Odoo chủ động gọi ra để gửi/nhận dữ liệu.

### 2.1. Adsroid AI Integration
**Mục đích:** Gửi dữ liệu hiệu suất để AI phân tích và đưa ra đề xuất tối ưu.

| Thông số | Chi tiết |
|---|---|
| **URL** | `https://rckoycauuwzdryvkjpac.supabase.co/functions/v1/adsroid` |
| **Phương thức** | `POST` |
| **Headers** | `Authorization: bearer {api_key}`, `Content-Type: application/json` |
| **Data Gửi** | `{ "organisation_id": "...", "project_id": "...", "message": "..." }` |
| **Data Nhận** | `{ "response": "JSON string chứa score, action, insight, new_budget" }` |

### 2.2. Google Ads API (Mutate - Thao tác Dữ liệu)
Sử dụng thư viện `google-ads-python` để gọi các dịch vụ ghi/sửa.

| Dịch vụ (Service) | Phương thức gọi | Dữ liệu chính gửi đi |
|---|---|---|
| **CampaignService** | `mutate_campaigns` | Trạng thái (Pause/Enable), Tên chiến dịch. |
| **CampaignBudgetService** | `mutate_campaign_budgets` | `amount_micros` (Ngân sách mới). |
| **AdGroupService** | `mutate_ad_groups` | Trạng thái, Loại nhóm quảng cáo. |
| **AdGroupAdService** | `mutate_ad_group_ads` | Nội dung Headlines, Descriptions cho RSA. |
| **AssetService** | `mutate_assets` | Logo, Business Name, Marketing Images. |

### 2.3. Google Ads API (Reporting - Đọc Dữ liệu)
| Dịch vụ (Service) | Phương thức gọi | Dữ liệu chính nhận về |
|---|---|---|
| **GoogleAdsService** | `search` (GAQL) | Clicks, Conversions, Cost, Impression Share, Lost IS (Rank/Budget). |

### 2.4. Google Ads Offline Conversions
**Mục đích:** Gửi dữ liệu đơn hàng thành công từ Odoo lên Google Ads.

| Thông số | Chi tiết |
|---|---|
| **Service** | `ConversionUploadService` |
| **Phương thức** | `upload_click_conversions` (POST qua gRPC) |
| **Data Gửi** | `gclid`, `conversion_action`, `conversion_value`, `conversion_date_time` |

### 2.5. Google Tag Manager (GTM) API
**Mục đích:** Kiểm tra cấu hình thẻ để đồng bộ về Odoo.

| Thông số | Chi tiết |
|---|---|
| **URL** | `https://tagmanager.googleapis.com/tagmanager/v2/accounts/...` |
| **Phương thức** | `GET` |
| **Dữ liệu nhận** | JSON danh sách Tags, Triggers và Variables. |

---

**Lưu ý:** Đối với Google Ads, các Endpoint thực tế được ẩn sau thư viện gRPC chính thức để đảm bảo bảo mật và hiệu năng.
