# -*- coding: utf-8 -*-
{
    'name': 'Combo to BOM Converter',
    'summary': 'Chuyển đổi sản phẩm Combo thành Định mức nguyên vật liệu (BOM)',
    'description': """
Combo to BOM Converter
======================
Module này cho phép chuyển đổi sản phẩm Combo (từ module combo_product) thành:
- Loại sản phẩm: Storable (có theo dõi tồn kho)
- Định mức nguyên vật liệu (BOM): Kit (phantom) - tự động giao các thành phần khi bán

Tính năng:
- Wizard chuyển đổi hàng loạt
- Button trực tiếp trên form sản phẩm
- Tự động tạo BOM lines từ Combo Items
    """,
    'author': 'HLV',
    'website': '',
    'category': 'Manufacturing/Manufacturing',
    'version': '18.0.1.0.0',
    'depends': ['combo_product', 'mrp'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/combo_to_bom_wizard_views.xml',
        'views/product_template_views.xml',
    ],
    'license': 'LGPL-3',
    'auto_install': False,
    'installable': True,
}
