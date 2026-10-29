# -*- coding: utf-8 -*-
import functools

from werkzeug.exceptions import Forbidden

from odoo.http import request


def internal_only(endpoint):
    """Chỉ nhân viên nội bộ được vào route; tài khoản portal / tự đăng ký nhận 403.

    auth="user" chỉ đòi đã đăng nhập, mà trang đăng nhập đang mở tự đăng ký tài khoản portal:
    người ngoài tự tạo tài khoản là xem được tồn kho và các loại giá. Đặt NGAY DƯỚI @http.route;
    functools.wraps giữ chữ ký gốc để Odoo vẫn lọc đúng tham số của route.
    """
    @functools.wraps(endpoint)
    def wrapper(*args, **kwargs):
        if not request.env.user._is_internal():
            raise Forbidden()
        return endpoint(*args, **kwargs)
    return wrapper
