# -*- coding: utf-8 -*-
{
    'name': 'HLV Hợp đồng',
    'summary': 'Hợp đồng mua bán / nguyên tắc từ mẫu Word (trộn thư), soạn mẫu trên Odoo, '
               'xuất Word/PDF/Excel hàng loạt',
    'description': """
Quản lý hợp đồng theo mẫu Word có trường trộn (MERGEFIELD), thay cho form Excel + Mail Merge.

- Mẫu: tải .docx giữ nguyên định dạng, import .doc/.docx, hoặc soạn trực tiếp trên Odoo.
- Hợp đồng: số tự sinh theo loại/năm, tổng tiền và số tiền bằng chữ tự tính.
- Giao diện là trang riêng /hop-dong (như /hoi-gia-ncc), không dùng form backend: danh sách,
  ngăn soạn hợp đồng, xem nhanh, xuất Word (zip khi nhiều) / PDF gộp để in / Excel theo cột form cũ,
  trình soạn mẫu bấm chèn biến.
- Phân quyền Nhân viên / Quản lý, thông tin bên bán lấy từ cấu hình công ty.
""",
    'author': 'HLV',
    'category': 'Sales',
    'version': '18.0.2.0.0',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'web'],
    'data': [
        'security/contract_security.xml',
        'security/ir.model.access.csv',
        'data/contract_sequence.xml',
        'data/company_data.xml',
        'data/template_data.xml',
        'data/report_data.xml',
        'views/contract_page_templates.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
}
