# -*- coding: utf-8 -*-
"""Phần dùng chung của các controller trang /hoi-gia-ncc."""

from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..services import sale_scope

API = "/api/hoi-gia-ncc"
PAGE_GROUPS = (
    "sales_team.group_sale_salesman",
    "purchase.group_purchase_user",
    "purchase_request.group_purchase_request_user",
)
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
        return any(user.has_group(group) for group in PAGE_GROUPS)

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
        if not inquiry or (code and (inquiry.sale_code or "").upper() != code.upper()):
            raise UserError("Không tìm thấy phiếu hỏi giá.")
        return inquiry
