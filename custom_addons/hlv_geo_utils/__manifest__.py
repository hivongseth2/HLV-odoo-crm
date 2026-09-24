{
    'name': 'HLV Geo Utils',
    'version': '18.0.1.0.0',
    'summary': 'Hàm thuần dùng chung: chuẩn hoá tên đối tác, đọc toạ độ, tính khoảng cách',
    'description': """
Addon chỉ chứa hàm thuần — không model, không view, không controller.

Lý do tồn tại: cả điều phối GIAO hàng (hlv_delivery_dispatch) và đi NHẬN hàng
(hlv_purchase_pickup) đều phải ghép tên đối tác Odoo với tên trên bản đồ, đọc chuỗi
toạ độ dán tay và đo khoảng cách giữa hai điểm. Hai chỗ định nghĩa cùng một quy tắc
chuẩn hoá tên là bug đang chờ xảy ra: điểm giao và điểm nhận của CÙNG một địa chỉ sẽ
sinh ra hai khoá so khớp khác nhau.

Dùng: from odoo.addons.hlv_geo_utils.tools.geo_text import normalize_name
""",
    'category': 'Technical',
    'author': 'HLV',
    'depends': ['base'],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
