{
    "name": "LLM Product Document Knowledge",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "summary": "Tự động đồng bộ tài liệu sản phẩm vào Knowledge Base cho AI",
    "description": """
Tự động tạo collection "Tài liệu sản phẩm" và đồng bộ tài liệu từ tab Tài liệu
của sản phẩm vào hệ thống RAG.

Mỗi resource sẽ được liên kết trực tiếp với sản phẩm, giúp AI biết tài liệu
thuộc về sản phẩm nào khi truy xuất kiến thức.
    """,
    "author": "HLV",
    "depends": ["llm_knowledge", "product"],
    "data": [
        "views/llm_resource_views.xml",
        "views/product_template_views.xml",
        "data/llm_product_document_data.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
