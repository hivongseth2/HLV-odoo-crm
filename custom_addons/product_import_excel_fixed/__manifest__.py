{
    "name": "Product Import Excel",
    "version": "1.0",
    "depends": ["base", "product", "stock", "combo_product"],
    "author": "ChatGPT",
    "category": "Tools",
    "description": "Import products and combo products from Excel file",
    "data": [
        "security/ir.model.access.csv",
        "wizard/product_import_wizard_view.xml",
        "views/product_import_action.xml",
        "views/product_template_views.xml"
    ],
    "installable": True,
    "auto_install": False
}