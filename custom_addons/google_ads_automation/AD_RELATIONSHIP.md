# Quan hệ giữa Nhóm quảng cáo (Ad Group) và Mẫu quảng cáo (Ad)

Tài liệu này mô tả quy tắc tương thích giữa Loại Nhóm quảng cáo (`type` trong `google.ads.ad.group`) và Loại Mẫu quảng cáo (`type` trong `google.ads.ad`) để đảm bảo việc đồng bộ lên Google Ads không bị lỗi.

## Bảng tra cứu tương thích (Compatibility Matrix)

| Loại Nhóm Quảng Cáo (Ad Group) | Các Loại Mẫu Quảng Cáo hỗ trợ (Ad Types) |
| :--- | :--- |
| **Tìm Kiếm Chuẩn** (`SEARCH_STANDARD`) | `RESPONSIVE_SEARCH_AD`, `EXPANDED_TEXT_AD`, `CALL_AD` |
| **Hiển Thị Chuẩn** (`DISPLAY_STANDARD`) | `RESPONSIVE_DISPLAY_AD`, `IMAGE_AD` |
| **Mua Sắm — Sản Phẩm** (`SHOPPING_PRODUCT_ADS`) | `SHOPPING_PRODUCT_AD` |
| **Khám Phá** (`DISCOVERY`) | `DISCOVERY_AD`, `DISCOVERY_CAROUSEL_AD` |
| **Video (In-stream, Bumper, Outstream)** | `VIDEO_AD` |
| **Khách Sạn** (`HOTEL_ADS`) | (Chưa hỗ trợ tạo mẫu Ad thủ công qua Odoo) |

## Quy tắc lọc dữ liệu (Filtering Logic)

Để tối ưu trải nghiệm người dùng và tránh chọn sai cặp loại dữ liệu không tương thích, hệ thống áp dụng logic lọc hai chiều:

### 1. Khi chọn Nhóm quảng cáo trước:
- Hệ thống sẽ tự động giới hạn danh sách **Loại quảng cáo** chỉ hiển thị những loại mà Nhóm đó hỗ trợ.
- *Ví dụ*: Nếu chọn nhóm "Tìm kiếm chuẩn", danh sách loại chỉ còn: RSA, Văn bản mở rộng, Cuộc gọi.

### 2. Khi chọn Loại quảng cáo trước:
- Hệ thống sẽ tự động lọc danh sách **Nhóm quảng cáo** chỉ hiển thị những nhóm có loại tương ứng.
- *Ví dụ*: Nếu chọn loại "RSA", danh sách Nhóm chỉ hiện các nhóm loại "Tìm kiếm chuẩn".

## Lưu ý đặc biệt về Performance Max (PMax)
Chiến dịch PMax không sử dụng Nhóm quảng cáo tiêu chuẩn mà sử dụng **Nhóm thành phần (Asset Group)**. Do đó:
- Không thể tạo Nhóm quảng cáo cho Campaign PMax.
- Không thể tạo Mẫu quảng cáo RSA/Display cho Campaign PMax (vì PMax tự động kết hợp các Asset).

---
*Tài liệu này được sử dụng làm cơ sở để triển khai logic Domain Filter trong mã nguồn.*
