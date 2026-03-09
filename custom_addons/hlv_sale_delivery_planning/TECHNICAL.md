# HLV Sale Delivery Planning - Technical Documentation

## 1. Mục đích Module
Cung cấp một Dashboard trực quan bằng OWL (Odoo Web Library) giúp Điều phối viên Kho và Quản lý Bán hàng theo dõi tiến độ chuẩn bị hàng hóa. Bảng điều khiển liên kết tự động giữa Đơn Bán (Sale Order) và Đơn Mua (Purchase Order) nếu PO được tạo từ nguồn SO (`origin`), đồng thời vẽ sơ đồ luồng lấy hàng/giao hàng.

## 2. Cấu trúc thư mục (Tree View)
```
hlv_sale_delivery_planning/
├── models/
│   ├── __init__.py
│   └── sale_order.py             ← Extend `sale.order`. Chỉ chứa fields bổ trợ và actions (như proxy method gọi xuống service).
├── services/                     ← [NEW] Lớp xử lý logic tập trung (Shared logic layer), không phụ thuộc UI trực tiếp.
│   ├── __init__.py
│   └── delivery_planner_service.py ← Chứa AbstractModel `hlv.delivery.planner.service` bóc tách query xử lý dữ liệu phức tạp.
├── static/
│   └── src/
│       └── components/
│           └── delivery_planner/ ← Giao diện OWL Components (JS, XML, SCSS).
├── views/
│   └── delivery_planner_views.xml ← Khai báo Menu, Action UI Client của OWL.
├── __init__.py
├── __manifest__.py
└── TECHNICAL.md                  ← Báo cáo cấu trúc Module.
```

## 3. Quy tắc Kiến trúc
- **Tách biệt Data và View**: Các Model chuẩn (như `sale.order`) tuyệt đối không gánh `method` xử lý logic lấy data cho UI quá 50 dòng. Mọi request khối lượng lớn (như vẽ cây Tree node, Filter nhiều chiều, Gom nhóm SO/PO) BẮT BUỘC phải chuyển sang `services/`.
- **Nguyên tắc DRY**: 
  - Các hàm tiện ích để parse Data (build Path, render status Text) nằm gọn trong `delivery_planner_service.py` dưới dạng các protected methods `_build_xxx()`.
  - Bên UI JS, các hàm Translating và formatting CSS Classes được thiết kế thuần tủy dưới dạng Object Helper.
- **Truy cập CSDL**: Luôn áp dụng phân trang (Pagination) ở cấp độ Backend Server thay vì tải All và chẻ page ở Client.

## 4. Luồng xử lý chính
2. **Fetch Data**: Component gọi hàm RPC `get_delivery_dashboard_data` từ frontend về backend.
3. **Chuyển tiếp Logic (Proxy)**: Hàm trong `sale_order.py` ngay lập tức bypass arguments sang Service `self.env['hlv.delivery.planner.service'].get_dashboard_data(...)`.
4. **Xử lý Dữ liệu**:
   - `_build_search_domain()`: Gom bộ lọc, tìm `sale.order` khớp.
   - `_process_order_batch()`: Lấy thông tin PO liên quan thông qua field `origin`. Tính Stock Status, Delivery Status.
    - `_build_flow_nodes()`: Truy vết Delivery `picking` (Outbound) và Receipt `picking` (Backorder, Return) thành Cây (Nodes Flow) liên thông bằng `parent_seq`, `return_of`.
    - `_fetch_packages_for_sales()`: Bóc tách dữ liệu từ `hlv_pack_sequence` để lấy mã Kiện, Số thứ tự kiện và danh sách sản phẩm bên trong từng thùng hàng.
    - `_calculate_po_and_stock_status()`: Mở rộng tính toán **Packing Status** (Đã đóng gói đủ, Đang đóng gói 1 phần, Chờ hàng về kho).
5. **Trả kết quả**: Service trả về Dictionary/List cho Model -> Model trả về JSON cho OWL Component.
6. **Hiển thị**: OWL re-render cấu trúc cây, đổ màu Color Indexing, Highlight hover và hiển thị **Package Item Cards**.

## 5. Hướng dẫn Mở rộng
- Nếu cần **thêm Bộ Lọc (Filter)**: Thêm trường Parameter ở JS RPC, sau đó xuống cập nhật hàm `_build_search_domain()` ở Service. Không cần đụng vào Core Sale Order.
- Nếu cần **thêm Giao diện Thẻ Thông báo Mới**: Cập nhật `delivery_planner.xml` và viết hàm Helper CSS tại `delivery_planner.js`. Đảm bảo JS Helper tuân thủ Regex và Ternary Operator an toàn.
