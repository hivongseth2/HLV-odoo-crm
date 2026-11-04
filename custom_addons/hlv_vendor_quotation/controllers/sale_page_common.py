# -*- coding: utf-8 -*-
"""Phần dùng chung của các controller trang /hoi-gia-ncc."""

from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..services import sale_scope
from ..services.access_setup import USER_GROUP

API = "/api/hoi-gia-ncc"
# Quản lý kế thừa Người dùng nên chỉ cần kiểm nhóm Người dùng.
PAGE_GROUP = USER_GROUP
SEARCH_LIMIT = 20


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class SalePageMixin:
    """Kiểm quyền vào trang + kiểm mã sale cho mọi API."""

    def _allowed(self):
        user = request.env.user
        return user.has_group(PAGE_GROUP)

    def _check(self, code=None):
        """Kiểm quyền vào trang; có truyền code thì trả mã sale đã kiểm (False = mọi mã)."""
        if not self._allowed():
            raise AccessError("Tài khoản chưa được cấp quyền hỏi giá nhà cung cấp.")
        if code is None:
            return None
        return sale_scope.validate_sale_code(request.env, code)

    def _get_inquiry(self, inquiry_id, code):
        """Phiếu thuộc phạm vi mã sale đã kiểm — không cho mở phiếu của sale khác bằng id."""
        inquiry = request.env["hlv.vendor.inquiry"].browse(to_int(inquiry_id)).exists()
        if not inquiry or (code and not self._inquiry_in_scope(inquiry, code)):
            raise UserError("Không tìm thấy phiếu hỏi giá.")
        return inquiry

    @staticmethod
    def _inquiry_in_scope(inquiry, code):
        """Phiếu là của mã sale code: mã sale của phiếu, hoặc phiếu có YCMH mà "Người yêu cầu" là sale này — đơn mua
        thuộc sale theo người yêu cầu của YCMH (cùng luật ô tìm số đơn mua, sale_page._purchase_order_inquiry_ids).
        sudo: sale chỉ đọc hạn chế YCMH."""
        if (inquiry.sale_code or "").upper() == code.upper():
            return True
        request_lines = inquiry.sudo().line_ids.request_line_ids
        return bool(request_lines) and bool(request_lines.search_count(
            [("id", "in", request_lines.ids)] + sale_scope.requester_scope_domain(code, "request_id.x_misa_requested_by"),
            limit=1))
