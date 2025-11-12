{
    "name": "HLV AI Sales Support",
    "version": "1.0.0",
    "category": "Sales",
    "summary": "AI-powered sales support with inventory check and supplier communication via Zalo",
    "description": """
        AI Sales Support Module
        =======================
        
        This module provides AI-powered sales support with the following features:
        - Receive product inquiries from sales team
        - Use ChatGPT to analyze and match products
        - Check inventory and pricing automatically
        - Contact suppliers via Zalo when stock is insufficient
        - Generate and send quotations back to sales team
        
        Key Features:
        - ChatGPT integration for product analysis
        - Automatic inventory checking
        - Zalo OA integration for supplier communication
        - Sales request tracking and management
        - Automated quotation generation
    """,
    "depends": [
        "base",
        "stock", 
        "sale",
        "product",
        "hlv_zalo_zns"  # Dependency on existing Zalo module
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/ai_sales_config_views.xml",
        "views/supplier_contact_views.xml", 
        "views/sales_request_views.xml",
        "views/product_inquiry_views.xml",
        "views/menu_views.xml",
        "data/ai_sales_config_data.xml",
    ],
    "installable": True,
    "application": True,
    "license": "LGPL-3",
    "external_dependencies": {
        "python": ["requests", "openai"]
    }
}