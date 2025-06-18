{
    "name": "Import Sale Orders from MISA API",
    "version": "1.0",
    "summary": "Import đơn hàng từ MISA thông qua API",
    "category": "Sales",
    "author": "HLV",
    "depends": ["sale", "base"],
    "data": [
        "security/ir.model.access.csv",
        "views/sale_api_import_wizard_view.xml",
        "views/sale_api_menu.xml"
    ],
    "installable": True,
    "application": False,
}