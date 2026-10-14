# -*- coding: utf-8 -*-
{
    "name": "HLV Kiểm map nhầm sản phẩm Shopee ↔ Odoo (AI)",
    "version": "18.0.1.1.0",
    "summary": "Claude so thành phần từng liên kết Sản phẩm Shopee với sản phẩm Odoo, tìm cặp map nhầm (vd combo khác món)",
    "description": """
Liên kết "Sản phẩm Shopee" (shopee.item) quyết định đơn Shopee về Odoo xuất hàng nào, và tồn của sản
phẩm Odoo nào được đẩy lên listing nào. Map nhầm (Shopee bán 1 pin + 1 sạc, Odoo gắn combo 1 máy + 1 pin
+ 1 sạc) là xuất nhầm hàng và đẩy tồn sai.

Một lần kiểm (Bán hàng → Cấu hình → Shopee → Kiểm map nhầm, hoặc chọn dòng ở danh sách Sản phẩm Shopee →
Hành động → Kiểm map nhầm với AI):

- Đọc tên, phân loại, SKU, mô tả của từng phân loại Shopee đang liên kết qua Shopee Open API v2
  (get_item_base_info, get_model_list), dùng kết nối và token của connector sale_shopee.
- Claude dựng thành phần thật trong hộp của từng bên (Odoo: dòng Combo Item hoặc BoM kit) rồi so từng món:
  loại, model, thông số, số lượng. Không so chữ — tên hai bên luôn viết khác nhau.
- Lỗi liên kết thấy ngay không cần AI: gắn SP tạm "Shopee Sales", một phân loại gắn nhiều sản phẩm,
  sản phẩm / phân loại không còn trên Shopee.
- Cặp đã kiểm ở lần trước mà không đổi gì thì dùng lại kết luận, không hỏi lại.
- Sửa ngay trên dòng: chọn "Sửa thành" → Áp dụng, rồi Chạy lại AI để kiểm cặp mới; xoá liên kết trỏ
  hàng / phân loại đã xoá trên Shopee. Hai thao tác ghi này cần nhóm "Sửa / xoá liên kết Shopee từ lần
  kiểm" (không ai có sẵn); chỉ kiểm thì quyền Quản lý bán hàng là đủ.

Tự kiểm định kỳ (Cài đặt → Bán hàng → Kiểm map nhầm Shopee, bật / tắt, chu kỳ ngày): có map nhầm thì
báo người có quyền sửa liên kết, nêu riêng số dòng mới so với lần trước.

Chạy nền bằng cron theo lượt ngắn (~2 phút rồi hẹn lượt sau), không giữ request của người dùng và không
chiếm worker cron lâu.
""",
    "author": "HLV",
    "category": "Sales/Sales",
    "license": "LGPL-3",
    "depends": [
        # shopee.shop / shopee.item và hàm gọi API có chữ ký + làm mới token.
        "sale_shopee",
        # Thành phần combo Odoo: dòng Combo Item (combo_product) và BoM kit (mrp, do hlv_combo_to_bom tạo).
        "combo_product",
        "mrp",
        # API key + client Claude dùng chung (services/claude_client.py).
        "hlv_product_agent",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/shopee_product_check_line_views.xml",
        "views/shopee_product_check_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
}
