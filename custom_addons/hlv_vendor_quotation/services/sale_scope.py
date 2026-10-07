# -*- coding: utf-8 -*-
"""Phạm vi mã sale của trang /hoi-gia-ncc — mượn nguyên cơ chế /misa_sale_status.

Mỗi tài khoản khai các mã sale MISA của mình ở res.users.x_misa_saler_codes; link riêng của
một sale là /hoi-gia-ncc?t=<token> (token băm từ mã, chỉ để không lộ mã trên URL). Quyền
THẬT nằm ở server: mọi API nhận mã sale và kiểm lại mã đó có thuộc tài khoản đang đăng nhập
không (misa_invoice_status_report._misa_invoice_validate_public_saler_code). Không chép lại
luật ở đây — gọi thẳng hàm bên đó.

Khác /misa_sale_status một chỗ: thu mua cũng xem được "Tất cả", vì thu mua là người duyệt
YCMH sinh ra từ mọi phiếu hỏi giá.
"""

from odoo.addons.misa_invoice_status_report.models.misa_invoice_public_api import (
    MISA_INVOICE_PUBLIC_ALL_SALERS as ALL_SALES,
)
from odoo.addons.misa_invoice_status_report.models.stock_picking import MISA_INVOICE_RECONCILE_GROUP
from odoo.exceptions import UserError

SEE_ALL_GROUPS = (
    MISA_INVOICE_RECONCILE_GROUP,
    "purchase.group_purchase_user",
    "purchase_request.group_purchase_request_user",
)


def can_see_all(env):
    """Tài khoản được chọn "Tất cả mã sale" không."""
    return any(env.user.has_group(group) for group in SEE_ALL_GROUPS)


def sale_code_options(env):
    """[{code, token}] các mã tài khoản đang đăng nhập được xem — đúng danh sách của /misa_sale_status."""
    return env["stock.picking"].get_misa_invoice_saler_code_registry_with_tokens()


def validate_sale_code(env, code):
    """Mã sale đã kiểm quyền. "Tất cả" (ALL_SALES) → False = không lọc theo sale.

    Mã rỗng / không thuộc tài khoản → UserError (do hàm của misa_invoice_status_report ném).
    """
    code = (code or "").strip()
    if code == ALL_SALES:
        if not can_see_all(env):
            raise UserError("Chỉ thu mua / quản lý được xem phiếu hỏi giá của mọi sale.")
        return False
    return env["stock.picking"]._misa_invoice_validate_public_saler_code(code)


def scope_domain(code, field="sale_code"):
    """Domain lọc theo mã đã kiểm (False = mọi mã). So không phân biệt hoa thường như MISA."""
    return [(field, "=ilike", code)] if code else []
