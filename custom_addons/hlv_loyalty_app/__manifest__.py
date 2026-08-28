{
    "name": "HLV - Loyalty Mobile App & Banners",
    "summary": "Quản lý Banners & Cấu hình cho Loyalty Mobile App (React Native)",
    "description": """
        Module mở rộng riêng cho Loyalty Mobile App:
        - Quản lý Banner khuyến mãi / ưu đãi hiển thị trên App Mobile.
        - Cung cấp REST API cho mobile app (/api/v1/loyalty/banners).
        - Độc lập hoàn toàn, không can thiệp logic hlv_loyalty core.
    """,
    "version": "18.0.1.0.0",
    "category": "Sales/Loyalty",
    "author": "HLV",
    "depends": ["hlv_loyalty", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/loyalty_store_data.xml",
        "views/loyalty_banner_views.xml",
        "views/loyalty_store_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}

