# Tài liệu Kỹ thuật (TECHNICAL.md) - hlv_barcode_shipper

## 1. Mục đích module
Module `hlv_barcode_shipper` cung cấp giao diện quét mã vạch chuyên biệt dành cho tài xế/shipper. Cho phép quét phiếu xuất kho (OUT), quét từng kiện hàng, chụp ảnh bàn giao, nhận hàng, giao hàng và trả hàng ngay trên điện thoại di động (thông qua camera hoặc máy quét chuyên dụng).

## 2. Quy tắc Kiến trúc & Phát triển

### OWL Components (Odoo 18)
- Bắt đầu từ Odoo 18, framework giao diện chính thức là OWL.
- **BẮT BUỘC:** Mọi giao diện mới, chức năng mở rộng UI hoặc các đoạn script phức tạp được thêm vào sau tài liệu này **PHẢI** được cấu trúc dưới dạng **OWL Components** để đảm bảo khả năng tái sử dụng và bảo trì.
- Hạn chế việc viết tiếp vào các file HTML thuần (`barcode_shipper_views.xml` phần template) kết hợp Vanilla JS khổng lồ như trước đây. Khi có thay đổi lớn, cần refactor các phần Vanilla JS hiện tại sang OWL.

### Tổ chức Thư mục & File (Dự kiến khi chuyển đổi sang OWL)
```
hlv_barcode_shipper/
├── static/src/
│   ├── components/       ← Thư mục chứa các OWL Components
│   │   ├── scanner/      ← Component quét mã chung
│   │   ├── receive/      ← Component tab Nhận hàng
│   │   ├── deliver/      ← Component tab Giao hàng
│   │   └── return/       ← Component tab Trả hàng
│   ├── css/              ← Styling chung (SASS/CSS)
│   └── js/               ← Scripts Vanilla JS hiện hữu (cần migrate dần)
```

### Nguyên tắc DRY & Tính kế thừa
- Các thao tác gọi API Backend (`/api/barcode/...`) phải được trừu tượng hóa (abstract) thành một file Service hoặc class chung, không viết trực tiếp fetch call rải rác trong các button click.
- Tái sử dụng các UI components như: Quét Camera (BarcodeDetector/ZXing), Modal xác nhận, Card danh sách phiếu (Pickings).

## 3. Luồng xử lý chính hiện hành
- Tab **Nhận hàng**: Quét/Tìm phiếu -> Chọn phiếu -> (Quét chi tiết kiện nếu config yêu cầu) -> Xác nhận lấy hàng từ kho.
- Tab **Giao hàng**: Quét phiếu PICK -> Quét từng kiện hàng -> Chụp ảnh phiếu bàn giao có chữ ký -> Xác nhận giao thành công.
- Tab **Trả hàng**: Chọn phiếu đã nhận -> Nhập lý do -> Xác nhận trả về kho.

*Tài liệu này được tạo ra để định hướng quá trình maintain và phát triển module trong tương lai (đặc biệt trong bối cảnh nâng cấp Odoo 18).*
