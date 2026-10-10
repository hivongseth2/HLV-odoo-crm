# -*- coding: utf-8 -*-
"""Điền bù bộ cột "sale đề xuất" trên YCMH — đã chuyển sang migrations/18.0.3.47.0 (bước 4).

Bản 18.0.3.47.0 bỏ field request_line_id của dòng phiếu hỏi giá (chọn nhiều NCC cho một sản phẩm), nên
code cũ ở đây không chạy được nữa. DB đã chạy bản này: 3.47 chỉ điền dòng còn trống, không đè gì.
"""


def migrate(cr, version):
    pass
