# -*- coding: utf-8 -*-
{
    "name": "HLV Trợ lý tạo mã hàng (Claude)",
    "version": "18.0.1.0.0",
    "summary": "Khung chat trên /search_stock: sale nhờ Claude chạy tại máy văn phòng kiểm trùng và tạo mã hàng MISA",
    "description": """
Sale chat trên trang tra tồn. Odoo xếp tin vào hàng chờ; agent cài trên máy có
Claude Code tự hỏi Odoo lấy tin, chạy Claude, rồi gửi câu trả lời về.

Agent chỉ gọi RA Odoo, máy văn phòng không mở cổng nào. Tài khoản MISA vẫn ở
Odoo: Claude gọi tool MISA qua Odoo, không bao giờ cầm token MISA.

Thay cho luồng tạo mã bằng ChatGPT của hlv_chatgpt.
    """,
    "author": "HLV",
    "category": "Inventory",
    # website_public_inventory_18: trang /search_stock để gắn khung chat.
    # misa_fetch_po_button: misa.api.utils — mọi tool MISA đều cần.
    # misa_invoice_status_report + hlv_sale_delivery_planning: hai field khai danh sách
    # sale dùng chung một tài khoản (x_misa_saler_codes, x_sale_plan_mention_names).
    "depends": [
        "website_public_inventory_18", "misa_fetch_po_button",
        "misa_invoice_status_report", "hlv_sale_delivery_planning",
    ],
    "data": [
        "security/product_agent_security.xml",
        "security/ir.model.access.csv",
        "data/product_agent_prompt_data.xml",
        "views/product_agent_views.xml",
        "views/product_chat_views.xml",
        "views/product_agent_log_views.xml",
        "views/product_agent_prompt_views.xml",
        "views/menu.xml",
        "views/chat_widget_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "hlv_product_agent/static/src/css/product_chat.css",
            "hlv_product_agent/static/src/js/product_chat.js",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
