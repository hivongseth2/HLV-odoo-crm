# -*- coding: utf-8 -*-
{
    "name": "HLV Trợ lý quản trị (Claude)",
    "version": "18.0.1.2.1",
    "summary": "Trang chat toàn màn cho quản trị: tạo báo giá, cơ hội trên MISA CRM, tra cứu Odoo, tạo mã hàng, tìm web",
    "description": """
Trang /tro-ly-quan-tri: chỉ khung chat (danh sách cuộc chat bên trái, cuộc đang mở ở giữa), chỉ
người có quyền "Trợ lý quản trị: Được dùng" vào được.

Odoo tự gọi Claude API bằng API key của Trợ lý tạo mã hàng (Cài đặt > Tồn kho), không qua máy
văn phòng. Kỹ năng:
- MISA CRM (hlv_misa_crm_connect): tra khách, giá cho khách, tìm / tạo / sửa cơ hội và báo giá,
  xem đơn hàng.
- Của trợ lý tạo mã hàng (hlv_product_agent): tạo / sửa mã hàng, combo; tra tồn, giá, lịch sử.
- Tìm và đọc web.

Mọi lệnh tạo / sửa trên MISA bị chặn ở Odoo nếu chưa được đề xuất cho người dùng xem ở câu trả
lời trước.
    """,
    "author": "HLV",
    "category": "Sales",
    # hlv_product_agent: API key, util gọi Claude, tool tạo mã + tra cứu, model phụ tra cứu.
    # hlv_misa_crm_connect: hlv.misa.crm.connect (khách, hàng, cơ hội, báo giá, đơn hàng).
    "depends": ["hlv_product_agent", "hlv_misa_crm_connect"],
    "data": [
        "security/admin_agent_security.xml",
        "security/ir.model.access.csv",
        "data/admin_agent_config_data.xml",
        "data/admin_agent_cron.xml",
        "views/admin_agent_config_views.xml",
        "views/admin_chat_session_views.xml",
        "views/admin_agent_memory_views.xml",
        "views/menu.xml",
        "views/chat_page_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "hlv_admin_agent/static/src/css/admin_chat.css",
            "hlv_admin_agent/static/src/css/admin_personal.css",
            "hlv_admin_agent/static/src/js/admin_chat_render.js",
            "hlv_admin_agent/static/src/js/admin_chat.js",
            "hlv_admin_agent/static/src/js/admin_personal.js",
        ],
    },
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
