# Hướng Dẫn Sử Dụng Chi Tiết — Google Ads Automation

---

## Mục lục

1. [Tổng quan module](#1-tổng-quan-module)
2. [Tài Khoản Google Ads](#2-tài-khoản-google-ads)
3. [Chiến Dịch, Nhóm QC, Mẫu QC](#3-chiến-dịch-nhóm-qc-mẫu-qc)
4. [Product Feed](#4-product-feed)
5. [Chiến Lược Tự Động](#5-chiến-lược-tự-động)
6. [Quy Tắc Tự Động (Rules)](#6-quy-tắc-tự-động-rules)
7. [Lịch Sử Quy Tắc (Log)](#7-lịch-sử-quy-tắc-log)
8. [Cron Job & Tự động hàng ngày](#8-cron-job--tự-động-hàng-ngày)
9. [Test bằng Demo Mode](#9-test-bằng-demo-mode)
10. [Checklist trước khi Go-Live](#10-checklist-trước-khi-go-live)

---

## 1. Tổng quan module

Module giúp **tự động hóa việc bật/tắt và tối ưu ngân sách Google Ads** dựa trên dữ liệu thực tế từ Odoo.

```
Odoo (Tồn kho + Giá + Doanh thu)
            ↓
    Smart Rule Engine
            ↓
Google Ads API (Pause / Enable / Adjust Budget)
```

**Luồng chính:**

| Bước | Việc làm | Ai làm |
|---|---|---|
| 1 | Kết nối tài khoản Google Ads | Người dùng (1 lần) |
| 2 | Sync campaigns từ Google về | Tự động / thủ công |
| 3 | Tạo Product Feed — liên kết SP ↔ Campaign | Người dùng |
| 4 | Tạo Chiến Lược → Sinh Rules tự động | Người dùng |
| 5 | Cron chạy hàng ngày: đánh giá rules, thực thi | Tự động |

---

## 2. Tài Khoản Google Ads

**Vị trí:** Google Ads > Cấu Hình > Tài Khoản API

Mỗi tài khoản Google Ads tương ứng 1 record ở đây.

### Các field

| Field | Ý nghĩa |
|---|---|
| **Tên Tài Khoản** | Tên nội bộ để phân biệt (VD: "Tài khoản chính HLV") |
| **Chế Độ Demo** | Bật để test không cần API thật (xem [Mục 9](#9-test-bằng-demo-mode)) |
| **Developer Token** | Lấy từ Google Ads Manager Account |
| **Client ID / Secret** | Lấy từ Google Cloud Console (OAuth2) |
| **Refresh Token** | Tạo qua OAuth flow |
| **Operating Customer ID** | ID tài khoản Ads cụ thể (không dấu gạch ngang, VD: `1234567890`) |
| **Login Customer ID (MCC)** | ID tài khoản quản lý nếu dùng MCC |

### Các nút hành động

- **Kiểm Tra Kết Nối** — Xác thực credentials, chuyển trạng thái sang `Đã Kết Nối` nếu thành công
- **Đồng Bộ Dữ Liệu** — Kéo toàn bộ Campaigns / Ad Groups / Ads + metrics ngày hôm qua về Odoo

### Trạng thái

| Trạng thái | Ý nghĩa |
|---|---|
| Nháp | Mới tạo, chưa test |
| Đã Kết Nối | Credentials OK, sẵn sàng sync |
| Lỗi | Credentials sai hoặc API từ chối |

> ⚠️ **Lưu ý bảo mật**: Các field Developer Token, Client Secret, Refresh Token được ẩn dạng password. Không chia sẻ thông tin này ra ngoài.

---

## 3. Chiến Dịch, Nhóm QC, Mẫu QC

**Vị trí:** Google Ads > Chiến Dịch / Nhóm Quảng Cáo / Quảng Cáo

Đây là dữ liệu được **sync tự động từ Google Ads** về Odoo, không cần nhập tay.

### Dữ liệu được sync

| Field | Nguồn |
|---|---|
| Tên, ID | Google Ads |
| Trạng thái (Enabled / Paused) | Google Ads |
| Loại kênh (Search, Display, PMax) | Google Ads |
| Clicks, Impressions, Cost | Metrics ngày hôm qua |
| Conversions | Metrics ngày hôm qua (cần Conversion Tracking) |

> **Lưu ý:** Dữ liệu này chỉ phản ánh **ngày hôm qua** (`YESTERDAY` trong GAQL). Mỗi lần nhấn "Đồng Bộ" hoặc cron chạy sẽ ghi đè metrics mới nhất.

### Thay đổi trạng thái

Khi Rule Engine xử lý (ở chế độ Live), trường `Trạng Thái` sẽ thay đổi trực tiếp trong Odoo và đồng thời gửi lệnh lên Google Ads.

---

## 4. Product Feed

**Vị trí:** Google Ads > Product Feed

Đây là **cầu nối** giữa Sản phẩm Odoo và Chiến dịch Google Ads. Mỗi dòng trong Feed = 1 sản phẩm đang được theo dõi.

### Tạo Feed mới

1. Nhấn **Mới**, đặt tên và chọn Tài Khoản Google Ads
2. Nhấn **➕ Thêm Sản Phẩm** để mở wizard:
   - Chọn thủ công từng sản phẩm, hoặc
   - Chọn **Danh mục** → nhấn **Thêm Tất Cả Từ Danh Mục**
   - Có thể lọc **Chỉ SP Còn Hàng** để bỏ qua sản phẩm hết hàng
3. Nhấn **🔄 Cập Nhật Tồn Kho** để làm mới dữ liệu từ kho Odoo

### Các cột dữ liệu trong Feed

| Cột | Nguồn | Ý nghĩa |
|---|---|---|
| Sản phẩm | Odoo | `product.template` |
| Mã SP | Odoo | `default_code` |
| Tồn Kho Thực Tế | Odoo `qty_available` | Số lượng trong kho ngay lúc này |
| Tồn Kho Dự Kiến | Odoo `virtual_available` | Tính cả hàng đang về |
| Giá Bán | Odoo `list_price` | Giá bán lẻ |
| Giá Vốn | Odoo `standard_price` | Giá nhập / chi phí |
| Biên LN (%) | Tự tính | `(Giá bán - Giá vốn) / Giá bán × 100` |
| TB Bán/Ngày | Tự tính | Tổng `qty_delivered` 30 ngày / 30 |
| Số Ngày Tồn | Tự tính | `Tồn kho / TB bán/ngày` |
| Trạng Thái Tồn | Tự tính | Xem bảng bên dưới |
| Chiến Dịch Liên Kết | Người dùng chọn | Map sản phẩm ↔ campaign |

### Trạng thái tồn kho (màu sắc)

| Badge | Điều kiện | Ý nghĩa |
|---|---|---|
| 🔴 Sắp hết | Tồn ≤ 0 hoặc < 7 ngày tồn | Cần dừng QC ngay |
| 🟡 Tồn thấp | 7–30 ngày tồn | Cần theo dõi |
| 🟢 Bình thường | 30–90 ngày tồn | Ổn định |
| 🔵 Tồn cao | > 90 ngày tồn | Nên đẩy mạnh QC |

### Map sản phẩm ↔ Campaign

Ở cột **Chiến Dịch Liên Kết**, click vào từng dòng sản phẩm và chọn campaign tương ứng. Một sản phẩm có thể gắn nhiều campaign (VD: Search + Performance Max).

> ⚠️ **Quan trọng:** Nếu không map campaign, Chiến Lược sẽ không thể sinh Rules cho sản phẩm đó.

---

## 5. Chiến Lược Tự Động

**Vị trí:** Google Ads > Chiến Lược Tự Động

Chiến Lược là nơi bạn **định nghĩa logic** mà hệ thống sẽ dùng để quyết định bật/tắt QC.

### Các loại chiến lược

| Loại | Logic | Khi nào dùng |
|---|---|---|
| 🔴 Bảo vệ hàng sắp hết | Tồn < ngưỡng thấp → Pause | Tránh bị đặt hàng khi hết hàng |
| 🟢 Đẩy hàng tồn cao | Tồn > ngưỡng cao → Enable + Tăng budget | Muốn giải phóng kho nhanh |
| 💰 Tối ưu lợi nhuận | CPA > max hoặc Margin < min → Pause | Tối ưu chi phí QC |
| 📈 Đẩy hàng mới | SP tạo trong N ngày gần nhất → Enable | Tự động bật QC cho hàng mới nhập |
| 🔄 Cân bằng tự động | Kết hợp cả 3 loại trên | Khuyến nghị cho hầu hết trường hợp |

### Cấu hình ngưỡng (Threshold)

Vào tab **Cấu Hình Ngưỡng**:

| Ngưỡng | Mặc định | Ý nghĩa |
|---|---|---|
| Ngưỡng Tồn Thấp | 20 | Dưới X cái = sắp hết |
| Ngưỡng Tồn Cao | 200 | Trên X cái = tồn đọng |
| Ngày Tồn Nguy Hiểm | 7 | < 7 ngày nữa hết hàng = khẩn cấp |
| Biên LN Tối Thiểu (%) | 15% | Margin thấp hơn → không nên chạy QC |
| CPA Tối Đa | 100.000đ | Chi nhiều hơn để có 1 đơn → không hiệu quả |
| ROAS Mục Tiêu | 3.0 | Thu 3đ cho mỗi 1đ chi |
| % Tăng Budget | 30% | Tăng thêm bao nhiêu % khi đẩy hàng tồn |
| % Giảm Budget | 30% | Giảm bao nhiêu % khi cần thu hẹp |
| SP Mới Trong (ngày) | 30 | SP tạo trong 30 ngày gần nhất = hàng mới |

### Quy trình kích hoạt

1. Tạo chiến lược, cấu hình ngưỡng
2. Nhấn **⚡ Sinh Rules Tự Động** → Hệ thống tạo rules cho từng sản phẩm trong Feed
3. Kiểm tra rules trong tab **Rules Tự Sinh**
4. Nhấn **▶ Kích Hoạt** → Chiến lược chuyển sang trạng thái `Đang Chạy`

### Chế độ Live

| Chế độ | Toggle | Hành vi |
|---|---|---|
| Dry-run (Mặc định) | Tắt | Rules đánh giá + ghi log, KHÔNG gửi lệnh lên Google |
| Live | **Bật** (ribbon đỏ) | Gửi lệnh Pause/Enable thật lên Google Ads |

> ✅ **Khuyến nghị**: Chạy Dry-run ít nhất 3–5 ngày, kiểm tra log xem hệ thống quyết định đúng không, rồi mới bật Live.

---

## 6. Quy Tắc Tự Động (Rules)

**Vị trí:** Google Ads > Quy Tắc Tự Động

Rules thường được **sinh tự động** từ Chiến Lược. Bạn cũng có thể tạo rule thủ công.

### Cấu trúc một Rule

```
NẾU [Điều kiện] THÌ [Hành động]

VD: NẾU tồn kho < 20 THÌ Pause campaign
```

### Các Điều Kiện có thể dùng

| Nhóm | Field | Ý nghĩa |
|---|---|---|
| **Tồn kho** | Tồn Kho Thực Tế | `qty_available` từ Odoo |
| | Số Ngày Tồn | Còn bao nhiêu ngày nữa hết hàng |
| | TB Bán/Ngày | Tốc độ bán trung bình 30 ngày |
| **Lợi nhuận** | Biên Lợi Nhuận (%) | `(Giá bán - Giá vốn) / Giá bán` |
| | Là Sản Phẩm Mới | SP tạo trong N ngày gần nhất |
| **Google Ads** | Chi Phí | Cost hôm qua |
| | Lượt Nhấp | Clicks hôm qua |
| | Lượt Hiển Thị | Impressions hôm qua |
| | Lượt Chuyển Đổi | Conversions hôm qua |
| | CPA | Cost / Conversions |

### Các Hành Động

| Hành động | Ý nghĩa |
|---|---|
| Tạm Dừng (Pause) | Dừng campaign |
| Bật Lại (Enable) | Kích hoạt campaign |
| Tăng Budget (%) | Tăng ngân sách theo % (cần Live mode) |
| Giảm Budget (%) | Giảm ngân sách theo % (cần Live mode) |
| Chỉ Thông Báo | Ghi log, không làm gì |

### Chạy thủ công

Mở 1 rule bất kỳ → Nhấn **▶ Chạy Thử Ngay** để kiểm tra ngay lập tức.

> 💡 **Mẹo**: Rules có badge xanh "Tự Sinh" là do Chiến Lược tạo ra. Không nên sửa tay — thay vào đó hãy điều chỉnh ngưỡng trên Chiến Lược rồi sinh lại.

---

## 7. Lịch Sử Quy Tắc (Log)

**Vị trí:** Google Ads > Lịch Sử Quy Tắc

Mỗi lần rule được chạy (thủ công hoặc qua cron), hệ thống ghi 1 dòng log.

### Ý nghĩa các trạng thái log

| Trạng thái | Ý nghĩa |
|---|---|
| ✅ Bình Thường | Rule chạy xong, không có đối tượng nào vi phạm điều kiện |
| ⚠️ Đã Xử Lý | Tìm thấy campaign vi phạm, đã thực thi hành động |
| ❌ Lỗi | Có lỗi khi gọi API Google Ads (chỉ xảy ra ở Live mode) |

### Thông tin trong mỗi log

- **Quy Tắc** — Rule nào được chạy
- **Thời Gian Chạy** — Khi nào
- **Đối Tượng Bị Tác Động** — Campaign / Ad Group nào bị xử lý
- **Ghi Chú Chi Tiết** — Giá trị thực tế vs ngưỡng, hành động đã làm

---

## 8. Cron Job & Tự động hàng ngày

Sau khi bật Chiến Lược, hệ thống chạy tự động mỗi ngày theo thứ tự:

```
00:00 — Sync metrics từ Google Ads (clicks, cost, conversions ngày hôm qua)
00:15 — Cập nhật tồn kho từ Odoo (qty_available, sale history)
00:30 — Đánh giá tất cả Rules → thực thi hành động → ghi log
```

### Bật Cron

Vào **Settings > Technical > Automation > Scheduled Actions** → tìm **"Google Ads: Đánh Giá Quy Tắc"** → Bật nút Active → đặt lịch chạy.

> ⚠️ Cron mặc định **tắt** khi cài module (để tránh chạy nhầm khi chưa cấu hình xong).

---

## 9. Test bằng Demo Mode

Dùng khi **chưa có tài khoản Google Ads thật**.

### Bước 1: Tạo tài khoản Demo

1. **Google Ads > Cấu Hình > Tài Khoản API** → **Mới**
2. Đặt tên bất kỳ
3. Bật toggle **Chế Độ Demo** → Ribbon vàng "DEMO MODE" xuất hiện, ô credentials ẩn đi
4. Nhấn **Kiểm Tra Kết Nối** → Thành công ngay
5. Nhấn **Đồng Bộ Dữ Liệu** → Hệ thống tạo:
   - 4 Campaigns mẫu (2 Search + 1 Display + 1 PMax)
   - 8 Ad Groups (2 mỗi campaign)
   - 12 Ads — tất cả có metrics ngẫu nhiên (clicks, cost, conversions...)

### Bước 2: Thiết lập Product Feed

1. **Google Ads > Product Feed** → **Mới** → Chọn tài khoản Demo
2. Nhấn **➕ Thêm Sản Phẩm** → Chọn sản phẩm từ Odoo
3. Ở mỗi dòng SP, chọn 1 trong 4 Campaign DEMO ở cột **Chiến Dịch Liên Kết**

### Bước 3: Tạo Chiến Lược

1. **Google Ads > Chiến Lược Tự Động** → **Mới**
2. Chọn loại: **🔄 Cân bằng tự động**
3. Chọn tài khoản Demo + Feed vừa tạo
4. Nhấn **⚡ Sinh Rules Tự Động**
5. Nhấn **▶ Kích Hoạt**

### Bước 4: Chạy thử & xem Log

1. **Google Ads > Quy Tắc Tự Động** → Mở rule bất kỳ
2. Nhấn **▶ Chạy Thử Ngay**
3. Vào **Google Ads > Lịch Sử Quy Tắc** → xem kết quả

> ℹ️ Demo mode không bao giờ gửi lệnh thật lên Google Ads, dù bật Live.

---

## 10. Checklist trước khi Go-Live

| Hạng mục | Kiểm tra |
|---|---|
| ✅ Tài khoản Google Ads kết nối thành công | Trạng thái = "Đã Kết Nối" |
| ✅ Sync campaigns về Odoo | Có data trong Google Ads > Chiến Dịch |
| ✅ Product Feed đã map đầy đủ SP ↔ Campaign | Mọi dòng SP đều có campaign liên kết |
| ✅ Chiến Lược đã kích hoạt, Rules đã sinh | Tab "Rules Tự Sinh" có dữ liệu |
| ✅ Chạy Dry-run ít nhất 3 ngày | Log hiển thị đúng sản phẩm/campaign |
| ✅ Conversion Tracking cài trên WordPress | Google Ads có dữ liệu Conversions ≠ 0 |
| ✅ Đơn hàng WooCommerce sync về Odoo | `avg_daily_sales` tính đúng |
| ✅ Bật Live mode | Ribbon đỏ trên Chiến Lược |
| ✅ Bật Cron Job | Settings > Scheduled Actions > Active |
