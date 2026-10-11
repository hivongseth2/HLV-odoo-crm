# -*- coding: utf-8 -*-
"""Bản 3.1: thêm nhóm biến "Hàng hoá"; biến Mặt hàng chính tạo ở bản 3.0 nằm ở nhóm Điều khoản
thì chuyển sang (chỉ đổi khi chưa ai tự chọn nhóm khác)."""


def migrate(cr, version):
    cr.execute(
        "UPDATE hlv_contract_template_variable SET section = 'goods' "
        "WHERE name = 'Mat_Hang_Chinh' AND section = 'terms'"
    )
