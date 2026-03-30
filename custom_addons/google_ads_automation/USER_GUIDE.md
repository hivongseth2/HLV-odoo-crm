# Hướng Dẫn Sử Dụng Chi Tiết — Google Ads Automation

---

## Mục lục

1. [Tổng quan module](#1-tổng-quan-module)
2. [Tài Khoản Google Ads & Adsroid AI](#2-tài-khoản-google-ads--adsroid-ai)
3. [Chiến Dịch, Nhóm QC, Mẫu QC (Dashboard KPI)](#3-chiến-dịch-nhóm-qc-mẫu-qc)
4. [Product Feed](#4-product-feed)
5. [Chiến Lược Tự Động](#5-chiến-lược-tự-động)
6. [Quy Tắc Tự Động (Rules)](#6-quy-tắc-tự-động-rules)
7. [Lịch Sử Quy Tắc (Log)](#7-lịch-sử-quy-tắc-log)
8. [Cron Job & Tự động hàng ngày](#8-cron-job--tự-động-hàng-ngày)
9. [Test bằng Demo Mode](#9-test-bằng-demo-mode)
10. [Checklist trước khi Go-Live](#10-checklist-trước-khi-go-live)

---

## 1. Tổng quan module

Module giúp **tự động hóa việc bật/tắt và tối ưu ngân sách Google Ads** dựa trên dữ liệu thực tế từ Odoo. Điểm khác biệt so với các module trước đây là hệ thống này mang lại giao diện Dashboard báo cáo thời gian thực, đồng thời tích hợp trợ lý AI **Adsroid** để phân tích chiến dịch tự động.

```
Odoo (Tồn kho + Giá + Doanh thu)
            ↓
    Smart Rule Engine / Adsroid AI
            ↓
Google Ads API (Pause / Enable / Adjust Budget)
```

**Luồng chính:**

| Bước | Việc làm | Ai làm |
|---|---|---|
| 1 | Kết nối tài khoản Google Ads và cấu hình Adsroid AI | Người dùng (1 lần) |
| 2 | Kéo / Đẩy campaigns từ Google (bao gồm ngân sách) | Tự động / thủ công |
| 3 | Tạo Product Feed — liên kết Sản phẩm Odoo ↔ Chiến dịch | Người dùng |
| 4 | Tạo Chiến Lược → Sinh Rules tự động hoặc dùng Insights AI | Người dùng |
| 5 | Cron chạy hàng ngày: đánh giá rules, thực thi Mutate | Tự động |

---

## 2. Tài Khoản Google Ads & Adsroid AI

**Vị trí:** Google Ads > Cấu Hình > Tài Khoản API

Mỗi tài khoản Google Ads tương ứng 1 bản ghi ở đây, nay được hiển thị dưới dạng Hero Header chuyên nghiệp.

### Các field quan trọng

| Nhóm | Field | Ý nghĩa |
|---|---|---|
| **Google Ads** | Chế Độ Demo | Bật để test hệ thống không cần liên kết API thật (xem [Mục 9](#9-test-bằng-demo-mode)) |
| | Developer Token / Client ID / Secret / Refresh Token | Lấy từ Google Cloud Console |
| | Operating Customer ID | ID tài khoản Ads cụ thể cần quản lý (không có dấu -) |
| | Login Customer ID (MCC) | (Optional) ID tài khoản Mcc nếu sử dụng MCC |
| | Merchant Center ID | Bắt buộc nếu tạo Chiến dịch Mua Sắm / PMax |
| **Adsroid AI** | Sử dụng Adsroid AI | Bật tích hợp Trợ lý AI Adsroid.com |
| | Adsroid API Key, Org ID, Project ID | Credentials lấy từ cổng thông tin Adsroid |
| | Auto Apply Adsroid Action | Tự động áp dụng các hành động Đề xuất của AI (ví dụ tự động Tạm dừng) ngay khi có kết quả phân tích |

### Hướng dẫn kiểm tra

1. **Xác Thực OAuth**: Để Odoo tự động lấy Refresh Token, chọn **Xác thực Google (OAuth)**.
2. **Kiểm tra kết nối**: Nhấn **Kiểm Tra Kết Nối**, hệ thống sẽ ping đến Google Ads API. Trạng thái sẽ update thành thẻ `Đã Kết Nối`.
3. **Đồng Bộ Dữ Liệu**: Kéo dữ liệu (Campaigns, Ad Groups, Ads) từ Google Ads về Odoo. Form Tài khoản sẽ cập nhật ngay lập tức các chỉ số `Tổng Chi Phí`, `Tổng Chuyển Đổi`, v.v.

> ⚠️ **Lưu ý bảo mật**: Toàn bộ Token và Secret được ẩn theo chuẩn Password.

---

## 3. Chiến Dịch, Nhóm QC, Mẫu QC

**Vị trí:** Google Ads > Các Chiến Dịch

Thay vì các trường hiển thị nhàm chán, nay danh sách và Form Chiến dịch được thiết kế thành **Performance Dashboard Dashboard** mang lại cái nhìn bao quát về Metrics.

### Hình ảnh giao diện
- **Hero Header**: Hiển thị Trạng thái (Xanh/Vàng/Đỏ), Campaign ID, và Mức độ phủ sóng (Reach Power).
- **KPI Metrics Ribbon**: Hiển thị rõ Clicks, Lượt Hiển Thị, Tổng Chi Phí, Lượt Chuyển Đổi với màu sắc đặc trưng của Google.

### Tạo mới & Mutate (Đẩy chiến dịch lên Google Ads)
1. Thêm mới Chiến dịch trực tiếp từ Odoo.
2. Các cấu hình chú ý trong tab **Cấu hình Google Ads**:
   - **Loại Kênh (Channel Type)**: Hỗ trợ PMax, Search, Display, Shopping...
   - **Ngân sách hàng ngày**: Cấu hình Ngân sách qua API. Trị số này sẽ tự convert ra micros (trên Google) và ngược lại khi lưu.
   - **Tên Thương hiệu & Logo (Cho PMax)**: Để vượt rào quy định Asset (Thương hiệu/Logo) của PMax, hệ thống sẽ thực thi transaction "Đồng thời" qua Mutate API. Bạn **bắt buộc** điền các trường này.
   - Quy định Quảng cáo Chính trị (EU Political Advertising): Odoo tự handle ẩn gán `DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING` để bypass validate của API Google (Bắt buộc từ tháng 09/2025).
3. Nhấn nút **Đồng bộ lên Google Ads** để thực thi Push Data ra ngoài.

### Trợ lý Adsroid AI (Hỏi AI)
Phía trên Form Chiến Dịch có nút **Hỏi Nhận Định Adsroid (AI)**. Khi nhấn:
- Hệ thống đóng gói: Data Campaign (Clicks/Chi phí) + Tình trạng tồn kho (từ Product Feed liên kết).
- Gửi sang AI Agent của Supabase.
- Hiển thị Insight và Điểm số vào trường HTML: *Adsroid AI Insight*.
- Nếu Tài Khoản bật `Auto Apply`, Odoo sẽ ngay lập tức tự ra lệnh `Pause` dựa trên kết quả AI.

---

## 4. Product Feed

**Vị trí:** Google Ads > Product Feed

Đây là khu vực tập hợp các dòng Danh mục Sản phẩm có tham gia vào luồng Quảng cáo.

### Tạo Feed
1. Nhấn **Mới**, đặt tên và gắn với 1 Tài khoản.
2. Form cung cấp cái nhìn tổng quát: Phần trăm `Critical` (Sắp hết/Nguy hiểm), `Low` (Thấp), `Healthy` (An toàn).
3. Sử dụng Wizard **Thêm Tất Cả Từ Danh Mục** để lọc nhanh.
4. Nút **Tự động Map Campaign**: Module sẽ tự động quét Mã SKU hoặc Tên SP để gán tự động với Chiến dịch tương ứng nếu bạn gõ tên Campaign đúng.

### Metrics Computed:
| Cột | Ý nghĩa |
|---|---|
| Tồn Kho Thực Tế | Odoo `qty_available` |
| Giá Bán / Vốn | Lấy từ Odoo `list_price` / `standard_price`. |
| Biên LN (%) | `(Giá bán - Giá vốn) / Giá bán × 100` |
| TB Bán/Ngày | Quét lịch sử SO Line (đã giao) trong 30 ngày. Đảm bảo chuẩn theo Multi-steps Delivery. |
| Số Ngày Tồn | `Tồn kho / TB bán/ngày` |
| Trạng Thái Tồn | Màu chỉ dẫn (Đỏ: Hàng nguy cấp, Vàng: Sắp hết, Xanh: Tốt). |

---

## 5. Chiến Lược Tự Động

**Vị trí:** Google Ads > Chiến Lược Tự Động

Tương tự phiên bản trước, hệ thống có nhiều "Vị tướng" xử lý.
- 🔴 Bảo vệ hàng sắp hết.
- 🟢 Đẩy hàng tồn cao.
- 💰 Tối ưu lợi nhuận (CPA/ROAS margin cutoff).
- 📈 Đẩy hàng mới.
- 🔄 Cân bằng tự động.

Nhấn **⚡ Sinh Rules Tự Động** để module duyệt từng Sản Phẩm trong Product Feed, phân tích Ngưỡng Cấu Hình để tạo ra bảng `Rules`. Phải chọn chế độ **LIVE** nếu muốn Rule thực thi thật lệnh Mutate lên Google.

---

## 6. Quy Tắc Tự Động (Rules)

**Vị trí:** Google Ads > Quy Tắc Tự Động

Các câu lệnh máy quét. VD: `NẾU tồn kho < 20 THÌ Pause campaign`. Có Nút `Chạy Thử Ngay` ngay trên UI Form của Rule để test ngay lập tức hành vi đánh giá logic Điều kiện với số thực Odoo Odoo so với Số ngưỡng mà không đợi Cron chạy.

---

## 7. Lịch Sử Quy Tắc (Log)

**Vị trí:** Google Ads > Lịch Sử Quy Tắc

Log ghi lại rành mạch hành động: Dry-Run (thử nghiệm) hay Gọi Mutate thật. Hiển thị ID và Error API nếu rớt.

---

## 8. Cron Job & Tự động hàng ngày

Có một Cron Program "Google Ads: Đánh Giá Quy Tắc", chạy hàng ngày để:
1. Load Metrics mới nhất.
2. Chạy check Rules.
3. Chạy lệnh Adsroid tự phân tích (nếu Auto Apply bật).

Vào **Settings > Technical > Scheduled Actions** để bật Cron Job này.

---

## 9. Test bằng Demo Mode

Thiết kế nhằm hỗ trợ bạn test Odoo mà không tốn tiền API Google thật.
- Bật `Chế Độ Demo` tại form **Tài khoản API**.
- Nhấn **Đồng bộ Dữ liệu**: Module tự sinh 4 Campaigns (có đủ Search, Display, PMax), 8 Ad Groups, và các đơn hàng ảo lưu tại `google.ads.conversion`.
- Nút **Đồng bộ lên Google Ads** hoạt động ở chế độ giả lập, chỉ cập nhật trạng thái Local về `PAUSED/ENABLED`.
- Trợ giúp quá trình Demo với khách hàng mượt mà, metrics nhảy số theo thiết kế HTML UI đẹp mắt.

---

## 10. Checklist trước khi Go-Live

| Hạng mục | Kiểm tra |
|---|---|
| ✅ Tài khoản Google Ads kết nối hoặc Bật Demo | Trạng thái = "Đã Kết Nối" |
| ✅ Cấu hình Adsroid | Đã nhập API Key và Project ID |
| ✅ Đồng bộ Campaign từ Goolge | Vào list Campaign thấy Metrics có Grid UI |
| ✅ Kiểm tra Product Feed | Các cột Tồn Kho / Biên Lợi Nhuận hiển thị màu đúng |
| ✅ Check Campaign Config | Ngân sách hàng ngày, Merchant Center (nếu Shopping) khai báo đủ |
| ✅ Chiến Lược Kích Hoạt | Bật chế độ "LIVE" màu đỏ |
| ✅ Hoàn tất | Bật Cron Job trên Odoo |

---
*Tài liệu được cập nhật tự động trong phiên bản Odoo 18.0 Workspace. Tích hợp UI Performance Dashboard & Adsroid AI.*
