# HLV Sale Delivery Planning - Technical Documentation

## 1. Mục đích Module
Cung cấp một Dashboard trực quan bằng OWL (Odoo Web Library) giúp Điều phối viên Kho và Quản lý Bán hàng theo dõi tiến độ chuẩn bị hàng hóa. Bảng điều khiển liên kết tự động giữa Đơn Bán (Sale Order) và Đơn Mua (Purchase Order) nếu PO được tạo từ nguồn SO (`origin`), đồng thời vẽ sơ đồ luồng lấy hàng/giao hàng.

## 2. Cấu trúc thư mục (Tree View)
```
hlv_sale_delivery_planning/
├── models/
│   ├── __init__.py
│   └── sale_order.py               ← Extend `sale.order`. Chỉ chứa fields bổ trợ và proxy action xuống service.
├── services/                       ← Lớp xử lý logic tập trung (Shared logic layer).
│   ├── __init__.py
│   ├── delivery_planner_service.py ← Orchestrator: `get_dashboard_data()` (gọi các service bên dưới).
│   ├── delivery_planner_domain.py  ← `_build_search_domain()` — xây domain lọc Sale Order.
│   ├── delivery_planner_stock.py   ← `_calculate_po_and_stock_status()` — tính tồn kho & packing.
│   ├── delivery_planner_fetch.py   ← `_fetch_pos_for_sales()`, `_fetch_attachments_for_pickings()`, `_fetch_packages_for_sales()`.
│   ├── delivery_planner_formatter.py ← `_format_dashboard_order()` — serialize SO → dict cho OWL.
│   └── delivery_planner_flow.py    ← `_build_flow_nodes()` — vẽ sơ đồ luồng outbound/return.
├── static/
│   └── src/
│       └── components/
│           └── delivery_planner/
│               ├── delivery_planner.scss         ← Styles toàn bộ component.
│               ├── delivery_planner_utils.js     ← Pure helper functions (translate*, get*BadgeClass, format*).
│               ├── delivery_planner.js           ← OWL Component class (delegate sang utils).
│               ├── delivery_planner_kpi.xml      ← Templates: KPIStockCards, KPIPackingCards.
│               ├── delivery_planner_filters.xml  ← Templates: ActiveFiltersBar, FilterToolbar.
│               ├── delivery_planner_so_card.xml  ← Templates: SOCard, PickingNodeReturn, PickingNodeOutbound.
│               ├── delivery_planner_drawer.xml   ← Template: Drawer (Offcanvas).
│               ├── delivery_planner_modal.xml    ← Template: PackageModal.
│               └── delivery_planner.xml          ← Main template: gọi các sub-template qua t-call.
├── views/
│   └── delivery_planner_views.xml  ← Khai báo Menu, Action UI Client của OWL.
├── __init__.py
├── __manifest__.py
└── TECHNICAL.md                    ← Tài liệu kỹ thuật module.
```

### Nguyên tắc tách file Python (services/)
Tất cả file trong `services/` dùng chung abstract model `hlv.delivery.planner.service` qua `_inherit`. Odoo ORM tự merge tất cả methods vào cùng một class khi khởi động — mỗi file chỉ chứa một nhóm method liên quan.

### Nguyên tắc tách file XML
OWL `<t t-call="TemplateName"/>` chia sẻ rendering context của caller (bao gồm biến `t-foreach`). Sub-templates **không** cần truyền tham số riêng — chúng truy cập trực tiếp `so`, `picking`, v.v. từ context.
Tất cả XML files phải được đăng ký trong `__manifest__.py` → `web.assets_backend`, sub-templates đăng ký **trước** main template.

### Nguyên tắc tách file JS
`delivery_planner_utils.js` export các pure functions. `delivery_planner.js` import và wrap chúng thành instance methods để OWL templates gọi qua `this.*`.

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
