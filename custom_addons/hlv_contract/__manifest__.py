# -*- coding: utf-8 -*-
{
    'name': 'HLV Hợp đồng',
    'summary': 'Hợp đồng mua bán / nguyên tắc, phụ lục, đề nghị thanh toán từ mẫu Word (trộn thư), soạn mẫu trên Odoo, '
               'xuất Word/PDF/Excel hàng loạt',
    'description': """
Quản lý hợp đồng theo mẫu Word có trường trộn (MERGEFIELD), thay cho form Excel + Mail Merge.

- Mẫu: tải .docx giữ nguyên định dạng, import .doc/.docx, hoặc soạn trực tiếp trên trang
  (bấm chèn biến, bảng hàng hoá dựng sẵn).
- Mỗi mẫu có bộ biến riêng, tự nhận từ trường trộn trong mẫu; người dùng tự đặt biến mới,
  sửa nhãn/kiểu/nhóm/mặc định. Biến tự điền: số HĐ, ngày ký, bên bán, bảng hàng, tổng tiền.
- Trang riêng /hop-dong (như /hoi-gia-ncc): bảng dữ liệu kiểu Excel theo từng mẫu (sửa tại ô),
  ngăn soạn hợp đồng (chọn khách, chọn sản phẩm, lấy hàng từ đơn bán, giá nhập sau VAT),
  xem nhanh, xuất Word (zip) / PDF gộp để in / Excel mỗi mẫu một sheet.
- Số hợp đồng theo khuôn của từng mẫu (ngày soạn, mã khách, số báo giá CRM), sửa tay được; tổng
  tiền và số tiền bằng chữ tự tính.
- Phụ lục căn cứ hợp đồng nguyên tắc, giấy đề nghị thanh toán căn cứ phụ lục / hợp đồng mua bán,
  thanh toán theo đợt (tỷ lệ hoặc số tiền, đã đề nghị / còn lại).
- Phân quyền Nhân viên / Quản lý, thông tin bên bán lấy từ cấu hình công ty.
- PDF dùng font Tinos (OFL) đóng gói sẵn để tiếng Việt không rơi dấu trên server Linux.
""",
    'author': 'HLV',
    'category': 'Sales',
    'version': '18.0.3.4.0',
    'license': 'LGPL-3',
    # sale: chọn hàng từ danh mục sản phẩm và lấy dòng hàng từ đơn bán
    'depends': ['base', 'mail', 'web', 'sale'],
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
