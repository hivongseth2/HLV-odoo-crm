{
    "name": "HLV Product Document Crawler",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "summary": "Tự động lấy tài liệu từ website (Hoàng Long Vũ, MecSu) và đẩy vào RAG Knowledge",
    "description": """
Crawler tự động:
  - Tìm sản phẩm trên website theo SKU (mã nội bộ Odoo = SKU WooCommerce)
  - Lấy mô tả, thông số kỹ thuật từ WooCommerce API
  - Tạo tài liệu .md và gắn vào tab Tài liệu của sản phẩm
  - Tự động tạo llm.resource và chạy lập chỉ mục RAG

Hỗ trợ cấu hình skip/limit để xử lý 50k+ sản phẩm theo batch nhỏ.
    """,
    "author": "HLV",
    "depends": ["llm_product_document", "product"],
    "external_dependencies": {"python": ["requests", "bs4"]},
    "data": [
        "security/ir.model.access.csv",
        "views/hlv_doc_crawler_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
